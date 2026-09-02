import { useEffect, useMemo, useState } from "react";
import { fetchFileContent } from "./api";
import type { ManagedFile } from "./types";

const TEXT_EXTENSIONS = new Set([
  "txt", "md", "csv", "tsv", "json", "xml", "yaml", "yml", "log", "ini", "toml",
  "js", "jsx", "ts", "tsx", "css", "html", "htm", "py", "rb", "go", "rs", "java",
  "c", "h", "cpp", "hpp", "sh", "sql",
]);

type PreviewKind = "image" | "pdf" | "text" | "audio" | "video" | "unsupported";

function extension(filename: string) {
  return filename.toLowerCase().split(".").pop() || "";
}

export function previewKind(file: Pick<ManagedFile, "filename" | "content_type">): PreviewKind {
  const contentType = (file.content_type || "").toLowerCase().split(";")[0].trim();
  const ext = extension(file.filename);
  if (contentType.startsWith("image/")) return "image";
  if (contentType === "application/pdf" || ext === "pdf") return "pdf";
  if (contentType.startsWith("audio/")) return "audio";
  if (contentType.startsWith("video/")) return "video";
  if (
    contentType.startsWith("text/")
    || ["application/json", "application/xml", "application/javascript", "application/x-yaml"].includes(contentType)
    || TEXT_EXTENSIONS.has(ext)
  ) return "text";
  return "unsupported";
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

export default function FileCard({ file, compact = false, onDelete }: { file: ManagedFile; compact?: boolean; onDelete?: (file: ManagedFile) => void }) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewText, setPreviewText] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState("");
  const kind = useMemo(() => previewKind(file), [file.filename, file.content_type]);

  function closePreview() {
    setPreviewUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return null;
    });
    setPreviewText(null);
  }

  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  async function preview() {
    setError("");
    setPreviewing(true);
    try {
      const blob = await fetchFileContent(file.id);
      closePreview();
      if (kind === "text") {
        const maxCharacters = 1024 * 1024;
        const text = await blob.text();
        setPreviewText(text.length > maxCharacters ? `${text.slice(0, maxCharacters)}\n\n[Preview truncated at 1 MB]` : text);
      } else {
        setPreviewUrl(URL.createObjectURL(blob));
      }
    } catch (err: any) {
      setError(err.message || "Could not preview file");
    } finally {
      setPreviewing(false);
    }
  }

  async function download() {
    setError("");
    try {
      const blob = await fetchFileContent(file.id, true);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = file.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err: any) {
      setError(err.message || "Could not download file");
    }
  }

  const previewOpen = previewUrl !== null || previewText !== null;
  const icon = kind === "image" ? "IMG" : kind === "pdf" ? "PDF" : kind === "audio" ? "AUD" : kind === "video" ? "VID" : kind === "text" ? "TXT" : "FILE";

  return <div className={`managed-file-card ${compact ? "compact" : ""}`}>
    <div className="managed-file-icon" aria-hidden>{icon}</div>
    <div className="managed-file-body">
      <div className="managed-file-name" title={file.filename}>{file.filename}</div>
      <div className="managed-file-meta">{formatBytes(file.size)} - {file.content_type || "Unknown type"}</div>
      {!!file.tags.length && <div className="managed-file-tags">{file.tags.map((tag) => <span className="tag" key={tag}>{tag}</span>)}</div>}
      {error && <div className="managed-file-error">{error}</div>}
    </div>
    <div className="managed-file-actions">
      {kind !== "unsupported" && <button type="button" className="ghost pill-action" onClick={preview} disabled={previewing}>{previewing ? "Opening..." : "Preview"}</button>}
      <button type="button" className="ghost pill-action" onClick={download}>Download</button>
      {onDelete && <button type="button" className="ghost pill-action danger" onClick={() => onDelete(file)}>Delete</button>}
    </div>
    {previewOpen && <div className="file-preview-backdrop" role="dialog" aria-modal="true" aria-label={`Preview ${file.filename}`} onClick={closePreview}>
      <div className={`file-preview-modal preview-${kind}`} onClick={(event) => event.stopPropagation()}>
        <div className="file-preview-header"><strong>{file.filename}</strong><div className="file-preview-header-actions"><button className="ghost" type="button" onClick={download}>Download</button><button className="ghost" type="button" onClick={closePreview}>Close</button></div></div>
        {kind === "image" && previewUrl && <img src={previewUrl} alt={file.filename} />}
        {kind === "pdf" && previewUrl && <object data={previewUrl} type="application/pdf" aria-label={`PDF preview of ${file.filename}`}><div className="file-preview-fallback"><p>This browser could not display the PDF inline.</p><button className="primary" type="button" onClick={download}>Download PDF</button></div></object>}
        {kind === "text" && previewText !== null && <pre className="file-preview-text">{previewText || "[Empty file]"}</pre>}
        {kind === "audio" && previewUrl && <div className="file-preview-media"><audio src={previewUrl} controls>Your browser cannot preview this audio file.</audio></div>}
        {kind === "video" && previewUrl && <div className="file-preview-media"><video src={previewUrl} controls>Your browser cannot preview this video file.</video></div>}
      </div>
    </div>}
  </div>;
}
