# Build do EXE (Windows)

Este guia gera uma distribuicao **sem necessidade de Python instalado** no PC do usuario final.

## 1. Resultado esperado
Pasta final:

`dist\LiveTradutor\`

Ela contem:
- `LiveTradutor.exe`
- dependencias Python empacotadas
- `piper\` (TTS local)

## 2. Instalar dependencias de build
```powershell
pip install -r requirements.txt
pip install -r requirements-build.txt
```

## 3. Gerar EXE
```powershell
py .\build_exe.py
```

Ou manualmente:
```powershell
py -m PyInstaller .\livetradutor.spec --noconfirm --clean
```

## 4. Executar app empacotado
```powershell
.\dist\LiveTradutor\LiveTradutor.exe
```

## 5. Entrega para usuario final
Entregue a pasta inteira:

`dist\LiveTradutor\`

Nao envie apenas o `.exe` sozinho.

## 6. Observacoes importantes
- Traducoes (Gemini/Groq/DeepSeek) ainda exigem internet e chave API.
- STT via Deepgram exige internet e chave `DEEPGRAM_API_KEY`.
- TTS (Piper) roda localmente.
- Arquivos de configuracao/log vao para:
  - `%APPDATA%\LiveTradutor\runtime_settings.json`
  - `%APPDATA%\LiveTradutor\live_translator.log`
