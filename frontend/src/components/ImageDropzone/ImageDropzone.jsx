import React, { useState, useCallback } from 'react';
import './ImageDropzone.css';

export default function ImageDropzone({ onImageDrop }) {
  const [isDragActive, setIsDragActive] = useState(false);

  const handleDragEnter = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      if (file.type.startsWith('image/')) {
        const reader = new FileReader();
        reader.onload = (event) => {
          onImageDrop(event.target.result, file.name);
        };
        reader.readAsDataURL(file);
      }
    }
  }, [onImageDrop]);

  return (
    <div 
      className={`image-dropzone ${isDragActive ? 'active' : ''}`}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="dropzone-content">
        <span className="dropzone-icon">🖼️</span>
        <span className="dropzone-text">Drop an image here for multimodal analysis</span>
      </div>
    </div>
  );
}
