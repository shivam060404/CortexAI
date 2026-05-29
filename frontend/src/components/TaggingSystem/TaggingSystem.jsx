import React, { useState } from 'react';
import './TaggingSystem.css';

export default function TaggingSystem({ tags, onTagsChange }) {
  const [inputValue, setInputValue] = useState('');

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      const newTag = inputValue.trim().replace(/^#/, '');
      
      if (newTag && !tags.includes(newTag)) {
        onTagsChange([...tags, newTag]);
      }
      setInputValue('');
    } else if (e.key === 'Backspace' && !inputValue && tags.length > 0) {
      onTagsChange(tags.slice(0, -1));
    }
  };

  const removeTag = (indexToRemove) => {
    onTagsChange(tags.filter((_, index) => index !== indexToRemove));
  };

  return (
    <div className="tagging-system">
      <div className="tags-container">
        {tags.map((tag, index) => (
          <span key={index} className="tag">
            <span className="tag-hash">#</span>{tag}
            <button className="tag-remove" onClick={() => removeTag(index)}>×</button>
          </span>
        ))}
        <input
          type="text"
          className="tag-input"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={tags.length === 0 ? "Add tags (press Enter)..." : ""}
        />
      </div>
    </div>
  );
}
