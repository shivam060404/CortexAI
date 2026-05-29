import React from 'react';
import Plot from 'react-plotly.js';

export default function ChartEmbed({ chartConfig }) {
  if (!chartConfig) return null;
  
  const { type, title, data } = chartConfig;
  
  let plotData = [];
  
  if (type === 'bar') {
    plotData = [{
      type: 'bar',
      x: data.labels || data.x || [],
      y: data.values || data.y || [],
      marker: { color: '#7c3aed' }
    }];
  } else if (type === 'line') {
    plotData = [{
      type: 'scatter',
      mode: 'lines+markers',
      x: data.x || [],
      y: data.y || [],
      line: { color: '#7c3aed' }
    }];
  } else if (type === 'pie') {
    plotData = [{
      type: 'pie',
      labels: data.labels || [],
      values: data.values || [],
      marker: { colors: ['#7c3aed', '#a78bfa', '#c4b5fd', '#ede9fe'] }
    }];
  } else if (type === 'scatter') {
    plotData = [{
      type: 'scatter',
      mode: 'markers',
      x: data.x || [],
      y: data.y || [],
      marker: { color: '#7c3aed', size: 8 }
    }];
  }

  return (
    <div className="chart-embed">
      <Plot
        data={plotData}
        layout={{
          title: title,
          paper_bgcolor: 'transparent',
          plot_bgcolor: 'transparent',
          font: { color: '#e0e0e8' },
          margin: { t: 40, r: 20, l: 40, b: 40 },
          autosize: true
        }}
        useResizeHandler={true}
        style={{ width: '100%', height: '100%', minHeight: '300px' }}
        config={{ displayModeBar: false }}
      />
    </div>
  );
}
