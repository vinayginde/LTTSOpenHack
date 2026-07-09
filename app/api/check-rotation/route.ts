import { promises as fs } from "fs";
import os from "os";
import path from "path";
import { NextRequest, NextResponse } from "next/server";
import { execFile } from "child_process";

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const pdfEntries = formData.getAll("pdfFiles");
    const excelEntry = formData.get("excelFile");

    const pdfFiles = pdfEntries.filter((entry): entry is File => entry instanceof File);

    if (pdfFiles.length === 0 || !(excelEntry instanceof File)) {
      return NextResponse.json(
        { error: "Please upload at least one PDF and an Excel file." },
        { status: 400 }
      );
    }

    const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "plotvisionaries-"));
    const pdfDir = path.join(tempDir, "pdfs");
    await fs.mkdir(pdfDir, { recursive: true });

    const savedPdfNames: string[] = [];
    for (const file of pdfFiles) {
      const safeName = file.name.replace(/[^a-zA-Z0-9._-]/g, "_");
      const destination = path.join(pdfDir, safeName);
      const buffer = Buffer.from(await file.arrayBuffer());
      await fs.writeFile(destination, buffer);
      savedPdfNames.push(safeName);
    }

    const excelPath = path.join(tempDir, "uploaded.xlsx");
    const excelBuffer = Buffer.from(await excelEntry.arrayBuffer());
    await fs.writeFile(excelPath, excelBuffer);

    const outputPath = path.join(tempDir, "rotated.xlsx");
    const rotationScriptPath = path.join(process.cwd(), "backend", "CheckRotation.py");
    const scalingScriptPath = path.join(process.cwd(), "backend", "CheckScaling.py");
    const pythonExecutable = path.join(
      process.cwd(),
      ".venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python"
    );

    const rotationResult = await new Promise<{ stdout: string; stderr: string }>((resolve, reject) => {
      execFile(
        pythonExecutable,
        [rotationScriptPath, pdfDir, excelPath, outputPath],
        { cwd: process.cwd() },
        (error, stdout, stderr) => {
          if (error) {
            reject(new Error(stderr || error.message));
            return;
          }

          resolve({ stdout, stderr });
        }
      );
    });

    const referencePdf = savedPdfNames[0];
    const scalingResult = await new Promise<{ stdout: string; stderr: string }>((resolve, reject) => {
      execFile(
        pythonExecutable,
        [scalingScriptPath, pdfDir, referencePdf],
        { cwd: process.cwd() },
        (error, stdout, stderr) => {
          if (error) {
            reject(new Error(stderr || error.message));
            return;
          }

          resolve({ stdout, stderr });
        }
      );
    });

    const parsedRotation = JSON.parse(rotationResult.stdout.trim());
    const parsedScaling = JSON.parse(scalingResult.stdout.trim());

    return NextResponse.json({
      ...parsedRotation,
      ...parsedScaling,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Processing failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
