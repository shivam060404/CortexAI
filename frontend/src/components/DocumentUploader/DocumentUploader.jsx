import { useState, useRef, useCallback } from 'react';
import { uploadDocument } from '../../services/api';
import './DocumentUploader.css';

// =============================================================================
// DocumentUploader — Multi-format file upload for research context
// =============================================================================
// Supports: PDF, DOCX, MD, TXT, CSV, PNG, JPG, WEBP
// Files are uploaded to the backend, parsed, and ingested into RAG.
// Images return base64 data for vision analysis.
// =============================================================================

const ACCEPTED_TYPES = [
  '.pdf', '.docx', '.doc', '.md', '.txt', '.csv', '.tsv',
  '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp',
];

const FILE_ICONS = {
  pdf: '📕', docx: '📘', doc: '📘', md: '📝', txt: '📄',
  csv: '📊', tsv: '📊', png: '🖼️', jpg: '🖼️', jpeg: '🖼️',
  gif: '🖼️', webp: '🖼️', bmp: '🖼️',
};

export default function DocumentUploader({ onFilesReady, sessionId = 'default', maxFiles = 5 }) {
  const [files, setFiles] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef(null);

  const handleFiles = useCallback(async (fileList) => {
    if (!fileList || fileList.length === 0) return;

    const newFiles = Array.from(fileList).slice(0, maxFiles - files.length);
    if (newFiles.length === 0) return;

    setIsUploading(true);

    const results = [];
    for (const file of newFiles) {
      const ext = file.name.split('.').pop().toLowerCase();
      const entry = {
        id: `${file.name}-${Date.now()}`,
        name: file.name,
        size: file.size,
        ext,
        icon: FILE_ICONS[ext] || '📄',
        status: 'uploading',
        error: '',
        result: null,
      };

      try {
        const res = await uploadDocument(file, sessionId);
        entry.status = 'ready';
        entry.result = res;
        results.push({
          filename: res.filename,
          file_type: res.file_type,
          text: res.preview || '',
          image_data: res.image_data || '',
          word_count: res.word_count,
          chunks_stored: res.chunks_stored,
        });
      } catch (err) {
        entry.status = 'error';
        entry.error = err.message;
      }

      setFiles(prev => [...prev, entry]);
    }

    setIsUploading(false);
    if (results.length > 0 && onFilesReady) {
      onFilesReady(results);
    }
  }, [files.length, maxFiles, sessionId, onFilesReady]);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    handleFiles(e.dataTransfer.files);
  }, [handleFiles]);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const removeFile = useCallback((id) => {
    setFiles(prev => prev.filter(f => f.id !== id));
  }, []);

  const formatSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="doc-uploader">
      {/* Drop zone */}
      <div
        className={`doc-dropzone ${isDragOver ? 'drag-over' : ''} ${isUploading ? 'uploading' : ''}`}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPTED_TYPES.join(',')}
          onChange={(e) => handleFiles(e.target.files)}
          hidden
        />
        <div className="dropzone-icon">📎</div>
        <div className="dropzone-text">
          {isUploading ? 'Uploading...' : 'Drop files or click to upload'}
        </div>
        <div className="dropzone-hint">
          PDF, DOCX, MD, TXT, CSV, Images — up to {maxFiles} files
        </div>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="doc-file-list">
          {files.map(file => (
            <div key={file.id} className={`doc-file-item ${file.status}`}>
              <span className="file-icon">{file.icon}</span>
              <div className="file-info">
                <div className="file-name">{file.name}</div>
                <div className="file-meta">
                  {formatSize(file.size)}
                  {file.status === 'ready' && file.result && (
                    <>
                      {file.result.word_count > 0 && ` · ${file.result.word_count.toLocaleString()} words`}
                      {file.result.chunks_stored > 0 && ` · ${file.result.chunks_stored} chunks indexed`}
                      {file.result.file_type === 'image' && ' · Vision analysis ready'}
                    </>
                  )}
                  {file.status === 'uploading' && ' · Uploading...'}
                  {file.status === 'error' && ` · Error: ${file.error}`}
                </div>
              </div>
              <button className="file-remove" onClick={() => removeFile(file.id)} title="Remove">×</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
