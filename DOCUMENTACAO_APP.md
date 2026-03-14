# LiveTradutor - Documentacao Completa

## 1. Visao Geral
O `LiveTradutor` e um aplicativo desktop em Python que:
- captura audio do sistema (WASAPI loopback / Stereo Mix),
- transcreve em streaming com Deepgram,
- traduz para Portugues Brasileiro via API (Gemini, Groq, DeepSeek),
- sintetiza fala com Piper TTS local,
- reproduz audio traduzido em tempo quase real.

Pipeline atual:

`Captura -> VAD -> Deepgram STT -> Traducao -> TTS -> Playback`

## 2. Arquitetura
Threads principais:
- `audio_capture_thread`
- `deepgram_thread`
- `translation_thread`
- `tts_thread`
- `playback_thread`
- `monitor_thread`

Filas:
- `audio_queue`
- `text_queue`
- `translated_queue`
- `speech_queue`

## 3. Requisitos (rodar por codigo-fonte)
- Windows 10/11 x64
- Python 3.12
- Dispositivo de captura de audio de sistema (WASAPI loopback ou Stereo Mix)
- Internet para STT (Deepgram) e traducao (Gemini/Groq/DeepSeek)

## 4. Instalacao e execucao
No diretorio do projeto:

```powershell
pip install -r requirements.txt
py .\main.py
```

## 5. Como usar
1. Abra o app.
2. Clique em `CONFIG`.
3. Configure:
   - `Deepgram API Key`
   - Provedor primario de traducao (`gemini`, `groq`, `deepseek`)
   - Chaves e modelo de cada provedor
   - `Fallback automatico` (recomendado: ligado)
4. Clique em `Salvar`.
5. Clique em `PLAY`.
6. Clique em `STOP` para encerrar o fluxo.

## 6. Configuracao de API e modelos
- `Fetch Gemini`, `Fetch Groq`, `Fetch DeepSeek`: atualizam a lista de modelos disponiveis.
- `Fetch All`: busca modelos de todos os provedores de traducao.
- `Test Primary`: testa apenas o provedor primario.
- `Test All`: testa todos os provedores sem fallback.

Observacao:
- Deepgram usa chave propria no campo `Deepgram API Key`.
- A transcricao usa modelo Deepgram (`nova-3`) com streaming e pontuacao.

## 7. Onde ficam os dados do app
Para evitar problemas de permissao, os dados vao para:

`%APPDATA%\LiveTradutor`

Arquivos principais:
- `runtime_settings.json` (config geral sem segredos em texto puro)
- `secrets.db` (chaves protegidas)
- `live_translator.log` (log de execucao)

## 8. Seguranca de chaves
As chaves sao armazenadas em `secrets.db` com protecao DPAPI do Windows.

- Nao ficam expostas em texto puro no JSON.
- O botao `Clear Keys` remove chaves e faz limpeza do banco.
- Sem a conta Windows do usuario, os segredos nao sao reutilizaveis em outra maquina.

## 9. TTS local (Piper)
O TTS roda localmente com:
- `piper\piper.exe`
- `piper\pt_BR-faber-medium.onnx`

Nao depende de API externa para sintese.

## 10. Logs e diagnostico
Arquivo:

`%APPDATA%\LiveTradutor\live_translator.log`

Eventos uteis:
- `capture.stats`
- `pipeline.queues`
- `pipeline.stt_text`
- `pipeline.translated`
- `pipeline.tts_ready`
- `playback.play_start / playback.play_done`

## 11. Solucao rapida de problemas
### 11.1 Nao transcreve
- Verifique `Deepgram API Key`.
- Confirme internet ativa.
- Verifique no log se houve reconexao Deepgram.

### 11.2 Nao traduz
- Teste `Test Primary` e `Test All`.
- Confirme chave e modelo do provedor.
- Ligue fallback automatico.

### 11.3 Sem audio de saida
- Verifique dispositivo de audio padrao do Windows.
- Confirme no log eventos `pipeline.tts_ready` e `playback.play_start`.

## 12. Variaveis de ambiente uteis
- `DEEPGRAM_API_KEY`
- `DEEPGRAM_MODEL`
- `DEEPGRAM_LANGUAGE`
- `GROQ_API_KEY`
- `GEMINI_API_KEY`
- `DEEPSEEK_API_KEY`
- `PIPER_MODEL_PATH`
- `PIPER_BINARY`
- `LIVETRADUTOR_HOME`

## 13. Distribuicao para usuario final
Use o guia `BUILD_EXE.md` para gerar o pacote `.exe` com todas as dependencias.

A entrega correta e a pasta inteira:

`dist\LiveTradutor\`
