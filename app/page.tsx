"use client";

import { ChangeEvent, useState } from "react";

export default function Home() {
  const [pdfFiles, setPdfFiles] = useState<File[]>([]);
  const [excelFile, setExcelFile] = useState<File | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [resultSummary, setResultSummary] = useState<string | null>(null);
  const [multiPageSummary, setMultiPageSummary] = useState<string | null>(null);
  const [scalingSummary, setScalingSummary] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [lastData, setLastData] = useState<any | null>(null);

  const handlePdfSelection = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    const pdfs = files.filter((file) => file.name.toLowerCase().endsWith(".pdf"));
    setPdfFiles(pdfs);
  };

  const handleExcelSelection = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setExcelFile(file);
  };

  const handleProcess = async () => {
    if (!pdfFiles.length || !excelFile) {
      return;
    }

    setIsProcessing(true);
    setErrorMessage(null);
    setResultSummary(null);
    setMultiPageSummary(null);
    setScalingSummary(null);

    const formData = new FormData();
    pdfFiles.forEach((file) => formData.append("pdfFiles", file));
    formData.append("excelFile", excelFile);

    try {
      const response = await fetch("/api/check-rotation", {
        method: "POST",
        body: formData,
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Processing failed");
      }

        setLastData(data);

      setResultSummary(`${data.count} rotated PDF${data.count === 1 ? "" : "s"} found.`);
      setMultiPageSummary(`${data.multi_page_count} PDF${data.multi_page_count === 1 ? "" : "s"} have more than one page.`);
      setScalingSummary(`${data.scaled_in_count} scaled in and ${data.scaled_out_count} scaled out.`);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Processing failed");
    } finally {
      setIsProcessing(false);
    }
  };

  const isReady = pdfFiles.length > 0 && excelFile;

  function RotationChart({ total, rotated }: { total: number; rotated: number }) {
    const notRotated = Math.max(0, total - rotated);
    const rPct = total ? Math.round((rotated / total) * 100) : 0;
    const nPct = total ? Math.round((notRotated / total) * 100) : 0;

    return (
      <div className="mt-2 space-y-2">
        <div className="text-sm text-slate-300">Rotated: {rotated} ({rPct}%)</div>
        <div className="w-full bg-slate-800 rounded-md h-4 overflow-hidden">
          <svg className="w-full h-4" viewBox="0 0 100 4" preserveAspectRatio="none">
            <rect x="0" y="0" width={`${rPct}%`} height="4" fill="rgb(52 211 153)" />
          </svg>
        </div>
        <div className="text-sm text-slate-300">Not rotated: {notRotated} ({nPct}%)</div>
        <div className="w-full bg-slate-800 rounded-md h-2 overflow-hidden">
          <svg className="w-full h-2" viewBox="0 0 100 2" preserveAspectRatio="none">
            <rect x="0" y="0" width={`${nPct}%`} height="2" fill="rgb(71 85 105)" />
          </svg>
        </div>
      </div>
    );
  }

  function ScalingChart({ scaledIn, scaledOut, total }: { scaledIn: number; scaledOut: number; total: number }) {
    const same = Math.max(0, total - (scaledIn + scaledOut));
    const inPct = total ? Math.round((scaledIn / total) * 100) : 0;
    const outPct = total ? Math.round((scaledOut / total) * 100) : 0;
    const samePct = total ? Math.round((same / total) * 100) : 0;

    return (
      <div className="mt-2 space-y-2">
        <div className="text-sm text-slate-300">Scaled in: {scaledIn} ({inPct}%)</div>
        <div className="w-full bg-slate-800 rounded-md h-3 overflow-hidden">
          <svg className="w-full h-3" viewBox="0 0 100 3" preserveAspectRatio="none">
            <rect x="0" y="0" width={`${inPct}%`} height="3" fill="rgb(250 204 21)" />
          </svg>
        </div>
        <div className="text-sm text-slate-300">Scaled out: {scaledOut} ({outPct}%)</div>
        <div className="w-full bg-slate-800 rounded-md h-3 overflow-hidden">
          <svg className="w-full h-3" viewBox="0 0 100 3" preserveAspectRatio="none">
            <rect x="0" y="0" width={`${outPct}%`} height="3" fill="rgb(244 63 94)" />
          </svg>
        </div>
        <div className="text-sm text-slate-300">Same size: {same} ({samePct}%)</div>
        <div className="w-full bg-slate-800 rounded-md h-2 overflow-hidden">
          <svg className="w-full h-2" viewBox="0 0 100 2" preserveAspectRatio="none">
            <rect x="0" y="0" width={`${samePct}%`} height="2" fill="rgb(71 85 105)" />
          </svg>
        </div>
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-10 text-slate-100 sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <section className="rounded-3xl border border-slate-800 bg-slate-900/80 p-8 shadow-2xl shadow-black/20 backdrop-blur">
          <div className="max-w-2xl">
            <p className="mb-3 text-sm font-semibold uppercase tracking-[0.3em] text-cyan-400">
              Document Intake Dashboard
            </p>
            <h1 className="text-3xl font-semibold sm:text-4xl">
              Upload your PDF folder and matching Excel sheet in one place.
            </h1>
            <p className="mt-4 text-base leading-7 text-slate-400">
              Drop in a directory of PDF files and the spreadsheet that maps the
              records so your workflow can begin without switching tools.
            </p>
          </div>
        </section>

        <section className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="space-y-6">
            <div className="rounded-3xl border border-slate-800 bg-slate-900 p-6 shadow-lg shadow-black/10">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-semibold">PDF folder</h2>
                  <p className="mt-1 text-sm text-slate-400">
                    Select the folder containing the PDF documents.
                  </p>
                </div>
                <span className="rounded-full bg-cyan-500/10 px-3 py-1 text-sm font-medium text-cyan-300">
                  Step 1
                </span>
              </div>

              <label className="flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-slate-700 bg-slate-950/70 px-6 py-10 text-center transition hover:border-cyan-400 hover:bg-slate-950">
                <input
                  type="file"
                  className="sr-only"
                  onChange={handlePdfSelection}
                  multiple
                  accept="application/pdf"
                />
                <span className="text-lg font-medium text-slate-100">
                  Choose PDF folder
                </span>
                <span className="mt-2 text-sm text-slate-400">
                  Supports folders with .pdf files.
                </span>
              </label>

              <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                <p className="text-sm font-medium text-slate-200">Selection</p>
                <p className="mt-1 text-sm text-slate-400">
                  {pdfFiles.length > 0
                    ? `${pdfFiles.length} PDF${pdfFiles.length > 1 ? "s" : ""} ready`
                    : "No PDF folder selected yet."}
                </p>
              </div>
            </div>

            <div className="rounded-3xl border border-slate-800 bg-slate-900 p-6 shadow-lg shadow-black/10">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-semibold">Excel sheet</h2>
                  <p className="mt-1 text-sm text-slate-400">
                    Upload the spreadsheet that should be used for matching.
                  </p>
                </div>
                <span className="rounded-full bg-violet-500/10 px-3 py-1 text-sm font-medium text-violet-300">
                  Step 2
                </span>
              </div>

              <label className="flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-slate-700 bg-slate-950/70 px-6 py-10 text-center transition hover:border-violet-400 hover:bg-slate-950">
                <input
                  type="file"
                  className="sr-only"
                  onChange={handleExcelSelection}
                  accept=".xlsx,.xls,.csv"
                />
                <span className="text-lg font-medium text-slate-100">
                  Upload Excel file
                </span>
                <span className="mt-2 text-sm text-slate-400">
                  Accepted formats: .xlsx, .xls, .csv
                </span>
              </label>

              <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                <p className="text-sm font-medium text-slate-200">Selection</p>
                <p className="mt-1 text-sm text-slate-400">
                  {excelFile ? excelFile.name : "No Excel sheet uploaded yet."}
                </p>
              </div>
            </div>
          </div>

          <aside className="rounded-3xl border border-slate-800 bg-slate-900 p-6 shadow-lg shadow-black/10">
            <h2 className="text-xl font-semibold">Ready to process</h2>
            <p className="mt-2 text-sm leading-6 text-slate-400">
              Once both files are ready, you can continue with your document
              workflow.
            </p>

            <div className="mt-6 space-y-3 rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-400">PDF documents</span>
                <span className="font-medium text-slate-100">{pdfFiles.length}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-400">Excel sheet</span>
                <span className="font-medium text-slate-100">
                  {excelFile ? "Attached" : "Pending"}
                </span>
              </div>
            </div>

            <button
              type="button"
              className="mt-6 w-full rounded-2xl bg-cyan-500 px-4 py-3 font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
              disabled={!isReady || isProcessing}
              onClick={handleProcess}
            >
              {isProcessing
                ? "Processing..."
                : isReady
                  ? "Start processing"
                  : "Upload both inputs to continue"}
            </button>

            {resultSummary ? (
              <p className="mt-4 rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-300">
                {resultSummary}
              </p>
            ) : null}

            {multiPageSummary ? (
              <p className="mt-3 rounded-2xl border border-cyan-500/30 bg-cyan-500/10 p-3 text-sm text-cyan-300">
                {multiPageSummary}
              </p>
            ) : null}

            {scalingSummary ? (
              <p className="mt-3 rounded-2xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-300">
                {scalingSummary}
              </p>
            ) : null}

            {/* Charts */}
            {lastData ? (
              <div className="mt-4 space-y-3">
                <div>
                  <h3 className="text-sm font-medium text-slate-200">Rotation</h3>
                  <RotationChart
                    total={pdfFiles.length}
                    rotated={lastData.count ?? 0}
                  />
                </div>

                <div>
                  <h3 className="text-sm font-medium text-slate-200">Scaling</h3>
                  <ScalingChart
                    scaledIn={lastData.scaled_in_count ?? 0}
                    scaledOut={lastData.scaled_out_count ?? 0}
                    total={pdfFiles.length}
                  />
                </div>
              </div>
            ) : null}

            {errorMessage ? (
              <p className="mt-4 rounded-2xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-300">
                {errorMessage}
              </p>
            ) : null}
          </aside>
        </section>
      </div>
    </main>
  );
}
