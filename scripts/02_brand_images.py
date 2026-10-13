#!/usr/bin/env python3
"""Gera as imagens de marca da integração a partir do SVG da Visão de Empresa.

Regras do home-assistant/brands:
  icon.png     256x256   · icon@2x.png  512x512   · proporção 1:1 obrigatória
  logo.png     menor lado 128..256      · logo@2x.png  menor lado 256..512
  PNG, com transparência, aparado (mínimo de espaço vazio nas bordas)
"""

import subprocess
import sys
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
SVG = Path("/Volumes/SSD-T1-01/CLAUDE-SSD/PROJECTS/VISAO_DE_EMPRESA/VISAO_DE_EMPRESA.svg")
DEST = RAIZ / "custom_components" / "mw_tuya" / "brand"
TMP = Path("/tmp/mw_tuya_brand_src.png")

DEST.mkdir(parents=True, exist_ok=True)

subprocess.run(["rsvg-convert", "-w", "4096", "-o", str(TMP), str(SVG)], check=True)
src = Image.open(TMP).convert("RGBA")

caixa = src.getbbox()
marca = src.crop(caixa)
print(f"rasterizado {src.size} -> aparado {marca.size}")


def quadrado(lado: int) -> Image.Image:
    w, h = marca.size
    escala = lado / max(w, h)
    novo = marca.resize((max(1, round(w * escala)), max(1, round(h * escala))), Image.LANCZOS)
    tela = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    tela.paste(novo, ((lado - novo.width) // 2, (lado - novo.height) // 2), novo)
    return tela


def por_altura(altura: int) -> Image.Image:
    w, h = marca.size
    return marca.resize((max(1, round(w * altura / h)), altura), Image.LANCZOS)


saidas = {
    "icon.png": quadrado(256),
    "icon@2x.png": quadrado(512),
    "logo.png": por_altura(256),
    "logo@2x.png": por_altura(512),
}
for nome, img in saidas.items():
    alvo = DEST / nome
    img.save(alvo, "PNG", optimize=True)
    menor = min(img.size)
    print(
        f"  {nome:14} {img.size[0]}x{img.size[1]}  menor_lado={menor}  {alvo.stat().st_size / 1024:.1f} kB"
    )

erros = []
for nome in ("icon.png", "icon@2x.png"):
    im = Image.open(DEST / nome)
    esperado = 256 if nome == "icon.png" else 512
    if im.size != (esperado, esperado):
        erros.append(f"{nome}: {im.size} != ({esperado},{esperado})")
for nome, lo, hi in (("logo.png", 128, 256), ("logo@2x.png", 256, 512)):
    im = Image.open(DEST / nome)
    menor = min(im.size)
    if not (lo <= menor <= hi):
        erros.append(f"{nome}: menor lado {menor} fora de {lo}..{hi}")
for nome in saidas:
    im = Image.open(DEST / nome)
    if im.mode != "RGBA":
        erros.append(f"{nome}: modo {im.mode}, esperado RGBA")
print("\nCONFERÊNCIA:", erros or "tudo dentro da regra")
sys.exit(1 if erros else 0)
