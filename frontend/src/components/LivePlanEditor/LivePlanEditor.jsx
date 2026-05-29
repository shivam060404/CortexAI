import React, { useState } from 'react';
import './LivePlanEditor.css';

export default function LivePlanEditor({ todos, onUpdatePlan }) {
  const [editingIndex, setEditingIndex] = useState(-1);
  const [editValue, setEditValue] = useState('');

  const handleEditClick = (idx, currentText) => {
    setEditingIndex(idx);
    setEditValue(currentText);
  };

  const handleSave = (idx) => {
    if (editValue.trim()) {
      const newTodos = [...todos];
      newTodos[idx].text = editValue.trim();
      onUpdatePlan(newTodos);
    }
    setEditingIndex(-1);
  };

  const handleDelete = (idx) => {
    const newTodos = [...todos];
    newTodos.splice(idx, 1);
    onUpdatePlan(newTodos);
  };

  const handleAdd = () => {
    const newTodos = [...todos, { text: 'New Task', status: 'pending', order: todos.length }];
    onUpdatePlan(newTodos);
    setEditingIndex(todos.length);
    setEditValue('New Task');
  };

  return (
    <div className="live-plan-editor">
      <div className="plan-editor-header">
        <h4 className="plan-title">Editable Research Plan</h4>
        <button className="add-task-btn" onClick={handleAdd}>+ Add Task</button>
      </div>
      
      <div className="plan-items">
        {todos.map((todo, idx) => (
          <div key={idx} className={`plan-item-row plan-${todo.status}`}>
            <span className="plan-status-icon">
              {todo.status === 'completed' ? '✓' : todo.status === 'in_progress' ? '🔄' : todo.status === 'failed' ? '✕' : '○'}
            </span>
            
            {editingIndex === idx ? (
              <div className="plan-edit-form">
                <input 
                  type="text" 
                  value={editValue} 
                  onChange={(e) => setEditValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleSave(idx);
                    if (e.key === 'Escape') setEditingIndex(-1);
                  }}
                  autoFocus
                />
                <button className="save-btn" onClick={() => handleSave(idx)}>Save</button>
              </div>
            ) : (
              <div className="plan-text-wrap" onClick={() => handleEditClick(idx, todo.text)}>
                <span className="plan-text">{todo.text}</span>
                {todo.status === 'pending' && <span className="edit-hint">Click to edit</span>}
              </div>
            )}
            
            {todo.status === 'pending' && editingIndex !== idx && (
              <button className="delete-task-btn" onClick={() => handleDelete(idx)} title="Remove task">×</button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
