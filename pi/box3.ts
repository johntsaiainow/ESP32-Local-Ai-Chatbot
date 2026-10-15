/** Pi CLI 1.2+ extension. Load explicitly with: pi -e ./pi/box3.ts */
import { Type } from "@earendil-works/pi-ai";
import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { fileURLToPath } from "node:url";

const client = fileURLToPath(new URL("../host/box3.py", import.meta.url));

export default function (pi: ExtensionAPI) {
  // Queue all calls so one serial client owns the port at a time.
  let queue: Promise<unknown> = Promise.resolve();
  function invoke(args: string[], signal?: AbortSignal): Promise<string> {
    const next = queue.catch(() => {}).then(async () => {
      if (signal?.aborted) throw new Error("BOX-3 request cancelled");
      if (!process.env.BOX3_PORT) throw new Error("Set BOX3_PORT before starting Pi");
      const result = await pi.exec(process.env.BOX3_PYTHON || "python3", [client, ...args],
                                   { signal, timeout: 240000 });
      if (result.code !== 0) throw new Error(result.stderr || "BOX-3 command failed");
      return result.stdout.trim();
    });
    queue = next;
    return next;
  }

  pi.registerTool(defineTool({
    name: "box3_display",
    label: "BOX-3 Display",
    description: "Show UTF-8 text and supported emoji on the USB ESP-BOX-3. Select the text language; limited to 1024 UTF-8 bytes and the visible screen area.",
    parameters: Type.Object({
      text: Type.String(),
      language: Type.Optional(Type.String({ description: "en, zh, zh-TW, ja, or ko" })),
    }),
    async execute(_id, args, signal) {
      await invoke(["display", "--language", args.language || "en", "--", args.text], signal);
      return { content: [{ type: "text", text: "Text displayed on BOX-3." }], details: {} };
    },
  }));

  pi.registerTool(defineTool({
    name: "box3_say",
    label: "BOX-3 Speak",
    description: "Speak text using the host's offline Piper adapter or configured BOX3_TTS_COMMAND and the BOX-3 speaker. Requires host speech packages/models; does not automatically read every agent reply aloud.",
    parameters: Type.Object({ text: Type.String(), language: Type.Optional(Type.String()) }),
    async execute(_id, args, signal) {
      await invoke(["say", "--language", args.language || "en", "--", args.text], signal);
      return { content: [{ type: "text", text: "Speech played on BOX-3." }], details: {} };
    },
  }));

  pi.registerTool(defineTool({
    name: "box3_listen",
    label: "BOX-3 Listen",
    description: "Record up to 10 seconds from BOX-3 and return English or Chinese text through offline Vosk or BOX3_STT_COMMAND. Use when the user asks to listen; no continuous recording.",
    parameters: Type.Object({
      language: Type.Optional(Type.String({ description: "en or zh" })),
      seconds: Type.Optional(Type.Number({ minimum: 0.1, maximum: 10 })),
    }),
    async execute(_id, args, signal) {
      const transcript = await invoke(["listen", "--language", args.language || "en",
                                      "--seconds", String(args.seconds ?? 5)], signal);
      return { content: [{ type: "text", text: transcript }], details: { transcript } };
    },
  }));

  pi.registerCommand("box-listen", {
    description: "Record five seconds and send the transcript to Pi: /box-listen en|zh",
    handler: async (args, ctx) => {
      try {
        const language = args.trim() || "en";
        if (!["en", "zh"].includes(language)) throw new Error("Use /box-listen en or /box-listen zh");
        ctx.ui.notify("Recording five seconds from BOX-3...", "info");
        const transcript = await invoke(["listen", "--language", language]);
        pi.sendUserMessage(transcript, { deliverAs: "followUp" });
      } catch (error) {
        ctx.ui.notify(String(error), "error");
      }
    },
  });
}
