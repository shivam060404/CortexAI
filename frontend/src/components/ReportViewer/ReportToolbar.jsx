import React from 'react';
import './ReportViewer.css';

export default function ReportToolbar({ onExportPDF, onExportPPTX, onExportHTML, onCopy }) {
  return (
    <div className="report-toolbar">
      <div className="toolbar-group">
        <button className="toolbar-btn" onClick={onCopy} title="Copy to clipboard">
          <span className="btn-icon">📋</span> Copy
        </button>
      </div>
      <div className="toolbar-group">
        <button className="toolbar-btn primary" onClick={onExportPDF} title="Download as PDF">
          <span className="btn-icon">📄</span> PDF
        </button>
        <button className="toolbar-btn" onClick={onExportPPTX} title="Download as PowerPoint">
          <span className="btn-icon">📊</span> PPTX
        </button>
        <button className="toolbar-btn" onClick={onExportHTML} title="Download as Interactive HTML">
          <span className="btn-icon">🌐</span> HTML
        </button>
      </div>
    </div>
  );
}
