import { promises as fs } from "fs";
import os from "os";
import path from "path";
import { spawn } from "child_process";
import { deflateRawSync } from "zlib";
import { NextRequest } from "next/server";

function sanitizeFileName(name: string) {
  return name.replace(/[^a-zA-Z0-9._-]/g, "_");
}

function getPythonExecutable(): string {
  return path.join(
    process.cwd(),
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python"
  );
}

const crcTable = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i += 1) {
    let c = i;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[i] = c >>> 0;
  }
  return table;
})();

function crc32(buffer: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function getDosDateTime(date: Date) {
  const year = Math.max(1980, date.getFullYear());
  const dosTime = (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
  const dosDate = ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  return { dosDate, dosTime };
}

async function createZipFromFolder(folderPath: string): Promise<Buffer> {
  const fileNames = (await fs.readdir(folderPath))
    .filter((name) => name.toLowerCase().endsWith(".pdf"))
    .sort();

  const localParts: Buffer[] = [];
  const centralParts: Buffer[] = [];
  let offset = 0;
  const now = new Date();
  const { dosDate, dosTime } = getDosDateTime(now);

  for (const fileName of fileNames) {
    const filePath = path.join(folderPath, fileName);
    const data = await fs.readFile(filePath);
    const compressed = deflateRawSync(data);
    const nameBuffer = Buffer.from(fileName);
    const checksum = crc32(data);

    const localHeader = Buffer.alloc(30);
    localHeader.writeUInt32LE(0x04034b50, 0);
    localHeader.writeUInt16LE(20, 4);
    localHeader.writeUInt16LE(0, 6);
    localHeader.writeUInt16LE(8, 8);
    localHeader.writeUInt16LE(dosTime, 10);
    localHeader.writeUInt16LE(dosDate, 12);
    localHeader.writeUInt32LE(checksum, 14);
    localHeader.writeUInt32LE(compressed.length, 18);
    localHeader.writeUInt32LE(data.length, 22);
    localHeader.writeUInt16LE(nameBuffer.length, 26);
    localHeader.writeUInt16LE(0, 28);

    localParts.push(localHeader, nameBuffer, compressed);

    const centralHeader = Buffer.alloc(46);
    centralHeader.writeUInt32LE(0x02014b50, 0);
    centralHeader.writeUInt16LE(20, 4);
    centralHeader.writeUInt16LE(20, 6);
    centralHeader.writeUInt16LE(0, 8);
    centralHeader.writeUInt16LE(8, 10);
    centralHeader.writeUInt16LE(dosTime, 12);
    centralHeader.writeUInt16LE(dosDate, 14);
    centralHeader.writeUInt32LE(checksum, 16);
    centralHeader.writeUInt32LE(compressed.length, 20);
    centralHeader.writeUInt32LE(data.length, 24);
    centralHeader.writeUInt16LE(nameBuffer.length, 28);
    centralHeader.writeUInt16LE(0, 30);
    centralHeader.writeUInt16LE(0, 32);
    centralHeader.writeUInt16LE(0, 34);
    centralHeader.writeUInt16LE(0, 36);
    centralHeader.writeUInt32LE(0, 38);
    centralHeader.writeUInt32LE(offset, 42);
    centralParts.push(centralHeader, nameBuffer);

    offset += localHeader.length + nameBuffer.length + compressed.length;
  }

  const centralDirectory = Buffer.concat(centralParts);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(fileNames.length, 8);
  end.writeUInt16LE(fileNames.length, 10);
  end.writeUInt32LE(centralDirectory.length, 12);
  end.writeUInt32LE(offset, 16);
  end.writeUInt16LE(0, 20);

  return Buffer.concat([...localParts, centralDirectory, end]);
}

export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const pdfEntries = formData.getAll("pdfFiles");
  const excelEntry = formData.get("excelFile");
  const pdfFiles = pdfEntries.filter((entry): entry is File => entry instanceof File);

  if (pdfFiles.length === 0) {
    return new Response(JSON.stringify({ error: "Please upload at least one PDF." }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!(excelEntry instanceof File)) {
    return new Response(JSON.stringify({ error: "Please upload the coordinate Excel file." }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "backplot-input-"));
  const outputTempDir = await fs.mkdtemp(path.join(os.tmpdir(), "backplot-output-"));
  const pdfDir = path.join(tempDir, "pdfs");
  const outputPdfDir = path.join(outputTempDir, "pdfs");

  try {
    await fs.mkdir(pdfDir, { recursive: true });
    await fs.mkdir(outputPdfDir, { recursive: true });

    for (const file of pdfFiles) {
      const safeName = sanitizeFileName(file.name);
      await fs.writeFile(path.join(pdfDir, safeName), Buffer.from(await file.arrayBuffer()));
    }

    const excelPath = path.join(tempDir, sanitizeFileName(excelEntry.name || "coordinates.xlsx"));
    await fs.writeFile(excelPath, Buffer.from(await excelEntry.arrayBuffer()));

    const scriptPath = path.join(process.cwd(), "backend", "Backplot-myExcel.py");
    const pythonExecutable = getPythonExecutable();

    await new Promise<void>((resolve, reject) => {
      const child = spawn(pythonExecutable, [scriptPath, pdfDir, excelPath, outputPdfDir], {
        cwd: process.cwd(),
      });
      let stderr = "";

      child.stdout.on("data", () => {
        // Drain progress output so large runs cannot block on a full stdout pipe.
      });

      child.stderr.on("data", (chunk: Buffer) => {
        stderr += chunk.toString();
      });

      child.on("close", (code) => {
        if (code !== 0) {
          reject(new Error(stderr || "Backplot failed."));
          return;
        }
        resolve();
      });
    });

    const zipBuffer = await createZipFromFolder(outputPdfDir);

    return new Response(zipBuffer, {
      headers: {
        "Content-Type": "application/zip",
        "Content-Disposition": 'attachment; filename="backplotted-pdfs.zip"',
      },
    });
  } catch (error) {
    return new Response(
      JSON.stringify({ error: error instanceof Error ? error.message : "Backplot failed." }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }
    );
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
    await fs.rm(outputTempDir, { recursive: true, force: true });
  }
}
