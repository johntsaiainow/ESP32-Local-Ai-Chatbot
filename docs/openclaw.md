# Connect Osiris to OpenClaw

Osiris supports OpenClaw as a reply backend on every firmware board target.
OpenClaw still runs on your computer, Raspberry Pi, or server. It does not run
inside the ESP32. Choose either direct Wi-Fi access from the device or the
optional Python host with local speech processing.

## Enable your Gateway

After installing and configuring OpenClaw with a working agent, merge these
fields into its existing Gateway configuration (keep your other settings):

```json5
{
  gateway: {
    mode: "local",
    port: 18789,
    bind: "lan",
    auth: { mode: "token", token: "YOUR_STRONG_GATEWAY_TOKEN" },
    http: { endpoints: { chatCompletions: { enabled: true } } }
  }
}
```

Restart your Gateway after applying the configuration. For a host script on the
same computer, keep `bind: "loopback"` instead. An ESP32 needs the server's LAN
IPv4 address or DNS hostname; `localhost` would mean the ESP32 itself.

This uses the official [Chat Completions endpoint](https://docs.openclaw.ai/gateway/openai-http-api)
and [Gateway configuration](https://docs.openclaw.ai/gateway/config-gateway).
The endpoint is disabled by default, and its Bearer token grants operator access
including the agent's enabled tools. Restrict port 18789 to trusted devices with
your firewall; do not forward it to the public internet. Plain HTTP sends the
token and conversation unencrypted, so use it only on a trusted private network.
HTTPS requires a valid certificate trusted by the firmware's CA bundle; self-signed
certificates are not accepted. Tokens saved on the ESP32 use ordinary device NVS.

## Direct ESP32 mode — no Python script

Flash the usual firmware for your board, then open **Settings → Setup**:

| Field | Value |
| --- | --- |
| Mode | `openclaw` |
| OpenClaw Gateway URL | `http://192.168.1.10:18789` (replace with your server) |
| OpenClaw token | The Gateway token from your own configuration |
| OpenClaw agent ID | `default`, or a configured agent ID |
| OpenAI API key | Required for speech recognition and speech synthesis |
| OpenAI transcription model | `gpt-4o-mini-transcribe`, or your available transcription model |
| Speech model ID | Your available OpenAI TTS model, e.g. `gpt-4o-mini-tts` |
| Voice | `alloy`, or another voice supported by your TTS model |

Save and leave Settings. The status bar shows `Via: openclaw`. Say your configured
wake phrase and ask a question. Replies retain the existing 30-second follow-up
window. The regular **Chat model ID** field is ignored in this mode; the selected
OpenClaw agent controls its backend model.

The flow is microphone → OpenAI transcription → OpenClaw agent → OpenAI speech →
device speaker. Audio is uploaded to OpenAI for transcription; OpenClaw receives
text, not a live audio stream. Model subscriptions configured inside OpenClaw do
not pay for the separate speech API calls. API keys and Gateway tokens are kept
separate; blank token input keeps the saved token and `-` clears it.

The URL may end in `/v1` or `/v1/`; enter the base URL rather than the full
`/chat/completions` path. Firmware accepts IPv4 or DNS names. Redirects are
refused so the Gateway credential cannot be forwarded to another endpoint.

## Optional host mode — local speech

Keep the device in `host` mode. Install the host dependencies and configure
Whisper/Piper as described in the main README, then run:

```bash
export OPENCLAW_GATEWAY_URL='http://127.0.0.1:18789'
read -rsp 'OpenClaw token: ' OPENCLAW_GATEWAY_TOKEN; echo
export OPENCLAW_GATEWAY_TOKEN
host/.venv/bin/python host/voice_agent.py --host 192.168.1.50 --provider openclaw
```

Replace the device address. For USB, replace `--host 192.168.1.50` with
`--port /dev/ttyACM0` (or your board's actual serial port). `--model openclaw/my-agent`
selects another agent; the default is `openclaw/default`. You can also set
`BOX3_OPENCLAW_MODEL`. No OpenAI API key is needed by this adapter when speech
runs locally. The Gateway's configured model provider still needs its own access.

Both clients keep bounded conversation history and send complete recent turns
on each request: four turns on ESP32, twelve on the host. They do not select a
persistent Gateway session or reuse the main OpenClaw chat session. Tools and
permissions come from the selected agent; client-side tool calls and audio
attachments in replies are not supported. Text now streams into a sentence speech
queue: earlier sentences may play before the final response completes. A failed
stream stops the remaining queue. See [voice latency](voice-latency.md).
Errors do not silently fall back to another provider.

## Troubleshooting

- **Connection failure / negative HTTP status:** check Gateway bind address,
  firewall, server IP, Wi-Fi and port. Device and server must be reachable.
- **HTTP 401/403:** check the Gateway token and authentication configuration.
- **HTTP 404/405:** check URL/port and enable `chatCompletions` on the Gateway.
- **HTTP 3xx:** enter the final Gateway URL directly; redirects are disabled.
- **Incomplete/non-text response:** inspect the agent's Gateway logs and tools.
- **Speech fails while chat works:** check the separate OpenAI speech key,
  model permissions, quota and device time for TLS.

Verification in this repository uses mocked Gateway responses and firmware
compilation. A live Gateway and physical microphone/speaker still need testing.
