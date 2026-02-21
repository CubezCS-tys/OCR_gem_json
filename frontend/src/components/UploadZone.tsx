'use client';

import { useRef, useState } from 'react';

const ALLOWED = ['.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp', '.bmp'];

interface Props {
  maxMb: number;
  onFile: (file: File) => void;
}

export default function UploadZone({ maxMb, onFile }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  function handleFiles(files: FileList | null) {
    if (!files || !files.length) return;
    onFile(files[0]);
  }

  return (
    <div className="bg-white rounded-2xl border border-parchment-dark p-6 shadow-sm">
      <div
        className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-all ${
          dragOver
            ? 'border-ember bg-ember-light/30'
            : 'border-gray-200 hover:border-ember hover:bg-parchment/50'
        }`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          handleFiles(e.dataTransfer.files);
        }}
      >
        <div className="flex justify-center mb-5">
          <div className={`w-16 h-16 rounded-2xl flex items-center justify-center transition-colors ${dragOver ? 'bg-ember/20' : 'bg-ember/10'}`}>
            <svg className="w-8 h-8 text-ember" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="17 8 12 3 7 8"/>
              <line x1="12" y1="3" x2="12" y2="15"/>
            </svg>
          </div>
        </div>
        <p className="font-semibold text-ink mb-1 text-base">Drag &amp; drop your file here</p>
        <p className="text-sm text-gray-400">
          or <span className="text-ember font-medium">browse files</span>
        </p>
        <input
          ref={inputRef}
          type="file"
          accept={ALLOWED.join(',')}
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        <div className="flex flex-wrap justify-center gap-2 mt-6">
          {['PDF', 'JPG', 'PNG', 'TIFF', 'WebP'].map((f) => (
            <span key={f} className="px-2.5 py-0.5 rounded-full bg-parchment text-ink text-xs font-medium">{f}</span>
          ))}
          <span className="px-2.5 py-0.5 rounded-full bg-ember-light text-ember-muted text-xs font-medium">Max {maxMb} MB</span>
        </div>
      </div>
    </div>
  );
}
