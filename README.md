# LiveTradutor

Aplicativo desktop de traducao em tempo real:
`Captura de audio do sistema -> STT (Deepgram) -> Traducao IA -> TTS (Piper) -> Reproducao`.

## Documentacao

- [DOCUMENTACAO_APP.md](DOCUMENTACAO_APP.md)
- [BUILD_EXE.md](BUILD_EXE.md)

## Rodar em desenvolvimento

```powershell
pip install -r requirements.txt
py .\main.py
```

## Build local do EXE

```powershell
py .\build_exe.py
```

Saida local:
`dist\LiveTradutor\LiveTradutor.exe`

## Publicar no GitHub + GitHub Releases (com .exe)

Este projeto ja inclui workflow automatico:
- `.github/workflows/release-windows.yml`

Ele compila no `windows-latest` e anexa no **GitHub Releases**:
- `LiveTradutor-vX.Y.Z-win64.zip`
- `LiveTradutor-vX.Y.Z-win64.sha256.txt`

### 1. Criar repo e enviar codigo

```powershell
git init
git add .
git commit -m "feat: LiveTradutor pronto para release"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/SEU_REPO.git
git push -u origin main
```

### 2. Criar release com tag

```powershell
git tag v1.0.0
git push origin v1.0.0
```

Depois disso, o GitHub Actions vai gerar a Release automaticamente.

## Seguranca

Arquivos locais sensiveis nao entram no git (via `.gitignore`):
- `runtime_settings.json`
- `secure_secrets.db`
- logs e artefatos de build
