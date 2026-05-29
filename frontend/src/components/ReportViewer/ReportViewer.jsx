import React from 'react';
import ChartEmbed from './ChartEmbed';
import ReportToolbar from './ReportToolbar';
import './ReportViewer.css';

export default function ReportViewer({ 
  htmlContent, 
  charts = [], 
  onExportPDF, 
  onExportPPTX, 
  onExportHTML,
  title = "Research Report"
}) {
  
  const handleCopy = () => {
    // Strip HTML for copy
    const temp = document.createElement('div');
    temp.innerHTML = htmlContent;
    navigator.clipboard.writeText(temp.innerText).then(() => {
      alert("Report copied to clipboard!");
    });
  };

  return (
    <div className="report-viewer-container">
      <div className="report-viewer-header">
        <h3>{title}</h3>
        <ReportToolbar 
          onCopy={handleCopy}
          onExportPDF={onExportPDF}
          onExportPPTX={onExportPPTX}
          onExportHTML={onExportHTML}
        />
      </div>
      
      <div className="report-viewer-body">
        <div 
          className="report-content markdown-body" 
          dangerouslySetInnerHTML={{ __html: htmlContent }} 
        />
        
        {charts.length > 0 && (
          <div className="report-charts-section">
            <h4>Generated Charts</h4>
            <div className="charts-grid">
              {charts.map((chart, idx) => (
                <ChartEmbed key={idx} chartConfig={chart} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
