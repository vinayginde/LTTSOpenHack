import { promises as fs } from "fs";
import os from "os";
import path from "path";
import { spawn } from "child_process";
import { NextResponse } from "next/server";

function getPythonExecutable(): string {
  const candidates = [
    process.env.PYTHON_PATH,
    process.env.PYTHON,
    path.join(process.cwd(), ".venv", "Scripts", "python.exe"),
    path.join(process.cwd(), ".venv", "bin", "python"),
    "python",
    "python3",
  ].filter(Boolean) as string[];

  return candidates[0];
}

function sanitizeFileName(name: string) {
  return name.replace(/[^a-zA-Z0-9._-]/g, "_");
}

function readPythonResult(stdout: string) {
  const trimmed = stdout.trim();
  if (!trimmed) {
    throw new Error("Python returned no output.");
  }

  try {
    return JSON.parse(trimmed);
  } catch {
    throw new Error(`Unable to parse Python output: ${trimmed}`);
  }
}

function runPythonScript(pythonExecutable: string, excelPath: string) {
  return new Promise<any>((resolve, reject) => {
    const child = spawn(pythonExecutable, ["-c", "import json, os, sys; import pandas as pd;\nexcel_path = sys.argv[1]\nif not os.path.exists(excel_path): raise SystemExit('File not found')\ndf = pd.read_excel(excel_path, engine='openpyxl')\n\ndef normalize_text(value):\n    return str(value).strip() if pd.notna(value) else ''\n\npid_column = None\nfor col in df.columns:\n    lower = str(col).strip().lower()\n    if lower in {'p&id no.', 'p&id no', 'p&id drg no.', 'p&id drg no', 'pid', 'p&id'}:\n        pid_column = col\n        break\n\ntag_column = None\nfor col in df.columns:\n    lower = str(col).strip().lower()\n    if lower in {'tag type', 'tag_type', 'tag'}:\n        tag_column = col\n        break\n\nif pid_column is None:\n    raise SystemExit('P&ID column not found')\nif tag_column is None:\n    raise SystemExit('Tag Type column not found')\n\ncounts = {'Instrument': 0, 'Equipment': 0, 'Pipe-run': 0}\nby_pid = {}\n\nfor _, row in df.iterrows():\n    pid = normalize_text(row[pid_column]) or 'Unknown'\n    tag = normalize_text(row[tag_column]).lower()\n    if tag in {'instrument'}:\n        bucket = 'Instrument'\n    elif tag in {'equipment'}:\n        bucket = 'Equipment'\n    elif tag in {'pipe-run', 'pipe run', 'pipe_run'}:\n        bucket = 'Pipe-run'\n    else:\n        continue\n\n    counts[bucket] += 1\n    if pid not in by_pid:\n        by_pid[pid] = {'Instrument': 0, 'Equipment': 0, 'Pipe-run': 0}\n    by_pid[pid][bucket] += 1\n\nordered = []\nfor pid, pid_counts in sorted(by_pid.items()):\n    ordered.append({'pid': pid, 'total': sum(pid_counts.values()), 'counts': pid_counts})\n\nprint(json.dumps({'total': int(df.shape[0]), 'counts': counts, 'by_pid': ordered}))" , excelPath], {
      cwd: process.cwd(),
      env: process.env,
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });

    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(stderr.trim() || "Failed to analyze Excel file."));
        return;
      }

      try {
        resolve(readPythonResult(stdout));
      } catch (error) {
        reject(error);
      }
    });
  });
}

export async function POST(request: Request) {
  try {
    const formData = await request.formData();
    const excelEntry = formData.get("excelFile");

    if (!(excelEntry instanceof File)) {
      return NextResponse.json({ error: "Please upload an Excel file." }, { status: 400 });
    }

    const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "stats-"));
    const safeName = sanitizeFileName(excelEntry.name);
    const excelPath = path.join(tempDir, safeName);

    await fs.writeFile(excelPath, Buffer.from(await excelEntry.arrayBuffer()));

    try {
      const pythonExecutable = getPythonExecutable();
      if (!pythonExecutable) {
        throw new Error("Python interpreter was not found.");
      }

      const result = await runPythonScript(pythonExecutable, excelPath);
      return NextResponse.json(result);
    } finally {
      await fs.rm(tempDir, { recursive: true, force: true });
    }
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Failed to analyze Excel file." },
      { status: 500 }
    );
  }
}
