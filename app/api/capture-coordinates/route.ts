import { promises as fs } from "fs";
import os from "os";
import path from "path";
import { NextRequest } from "next/server";
import { spawn } from "child_process";

export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const pdfEntries = formData.getAll("pdfFiles");
  const pdfFiles = pdfEntries.filter((entry): entry is File => entry instanceof File);

  if (pdfFiles.length === 0) {
    return new Response(JSON.stringify({ error: "Please upload at least one PDF." }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      const send = (obj: object) =>
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(obj)}\n\n`));

      const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "plotvisionaries-"));
      const pdfDir = path.join(tempDir, "pdfs");
      await fs.mkdir(pdfDir, { recursive: true });

      try {
        // Write PDFs to temp dir
        for (const file of pdfFiles) {
          const safeName = file.name.replace(/[^a-zA-Z0-9._-]/g, "_");
          await fs.writeFile(path.join(pdfDir, safeName), Buffer.from(await file.arrayBuffer()));
        }

        // Write Excel if provided
        let excelPath: string | null = null;
        const excelEntry = formData.get("excelFile");
        if (excelEntry instanceof File) {
          const safeName = excelEntry.name.replace(/[^a-zA-Z0-9._-]/g, "_");
          excelPath = path.join(tempDir, safeName);
          await fs.writeFile(excelPath, Buffer.from(await excelEntry.arrayBuffer()));
        }

        const outputPath = path.join(tempDir, "capture_coordinates.xlsx");
        const scriptPath = path.join(process.cwd(), "backend", "CaptureCoordinates.py");
        const pythonExecutable = path.join(
          process.cwd(),
          ".venv",
          process.platform === "win32" ? "Scripts/python.exe" : "bin/python"
        );

        const args = excelPath
          ? [scriptPath, pdfDir, outputPath, excelPath]
          : [scriptPath, pdfDir, outputPath];

        await new Promise<void>((resolve, reject) => {
          const py = spawn(pythonExecutable, args, { cwd: process.cwd() });
          let stderr = "";
          let stdoutBuffer = "";

          py.stdout.on("data", (data: Buffer) => {
            stdoutBuffer += data.toString();
            const lines = stdoutBuffer.split("\n");
            stdoutBuffer = lines.pop() ?? ""; // keep incomplete line

            for (const line of lines) {
              if (line.startsWith("PROGRESS:")) {
                const [, file, completed, total] = line.split(":");
                send({ type: "file_done", file, completed: +completed, total: +total });
              }
            }
          });

          py.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
          py.on("close", (code) => {
            if (code !== 0) reject(new Error(stderr || "Python script failed"));
            else resolve();
          });
        });

        // Send the Excel file as base64 in the final event
        const fileData = await fs.readFile(outputPath);
        send({ type: "complete", file_b64: fileData.toString("base64") });

      } catch (err) {
        send({ type: "error", error: String(err) });
      } finally {
        await fs.rm(tempDir, { recursive: true, force: true });
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}