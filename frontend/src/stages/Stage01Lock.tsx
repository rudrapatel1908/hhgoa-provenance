import { useCallback, useRef, useState } from "react";
import styles from "./Stage01Lock.module.css";

interface Props {
  image: File | null;
  onImageSelected: (file: File) => void;
  onBegin: () => void;
}

// Client-side checks only mirror what the backend will reject anyway
// (INPUT_VALIDATION reads the file itself) -- this is just fast, local
// feedback before spending a round trip; the real validation is still
// the backend's, once BEGIN TRACE is pressed.
const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];

export function Stage01Lock({ image, onImageSelected, onBegin }: Props) {
  const [isDragging, setIsDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [dimensions, setDimensions] = useState<{ w: number; h: number } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const acceptFile = useCallback((file: File) => {
    if (!ACCEPTED_TYPES.includes(file.type)) {
      setLocalError("Unsupported format. Use JPG, PNG, or WebP.");
      return;
    }
    setLocalError(null);
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    const img = new Image();
    img.onload = () => setDimensions({ w: img.width, h: img.height });
    img.src = url;
    onImageSelected(file);
  }, [onImageSelected]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files?.[0];
      if (file) acceptFile(file);
    },
    [acceptFile],
  );

  return (
    <section className={styles.stage}>
      <div className={styles.copy}>
        <p className={styles.eyebrow}>01 — LOCK / ENTRY</p>
        <h1 className={styles.title}>The web leaves traces.</h1>
        <p className={styles.sub}>Discover public media. Verify the source.</p>
      </div>

      <div
        className={`${styles.dropzone} ${isDragging ? styles.dragging : ""} ${
          image ? styles.hasImage : ""
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label="Upload public image"
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="visually-hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) acceptFile(file);
          }}
        />

        {previewUrl ? (
          <div className={styles.previewWrap}>
            <div className={styles.frame}>
              <img src={previewUrl} alt="" className={styles.previewImg} />
              <span className={`${styles.corner} ${styles.cornerTL}`} />
              <span className={`${styles.corner} ${styles.cornerTR}`} />
              <span className={`${styles.corner} ${styles.cornerBL}`} />
              <span className={`${styles.corner} ${styles.cornerBR}`} />
            </div>
            <div className={styles.fileInfo}>
              <span className={`mono ${styles.filename}`}>{image?.name}</span>
              {dimensions && (
                <span className={`mono ${styles.dims}`}>
                  {dimensions.w}×{dimensions.h}
                </span>
              )}
            </div>
          </div>
        ) : (
          <>
            <p className={styles.dropLabel}>UPLOAD PUBLIC IMAGE</p>
            <p className={styles.dropHint}>Drop an image, or click to browse</p>
          </>
        )}
      </div>

      {localError && <p className={styles.error}>{localError}</p>}

      <div className={styles.actions}>
        <button
          type="button"
          className={styles.cta}
          disabled={!image}
          onClick={onBegin}
        >
          BEGIN TRACE →
        </button>
        <span className={`mono ${styles.readyLabel}`}>
          {image ? "SYSTEM READY" : "AWAITING INPUT"}
        </span>
      </div>
    </section>
  );
}
