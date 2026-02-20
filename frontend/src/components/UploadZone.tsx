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
    <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
      <div
        className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors ${
          dragOver ? 'border-indigo-400 bg-indigo-50' : 'border-gray-300 hover:border-indigo-400 hover:bg-gray-50'
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
        <div className="flex justify-center mb-4">
          <div className="w-14 h-14 bg-indigo-50 rounded-full flex items-center justify-center">
            <svg className="w-7 h-7 text-indigo-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="17 8 12 3 7 8"/>
              <line x1="12" y1="3" x2="12" y2="15"/>
            </svg>
          </div>
        </div>
        <p className="font-semibold text-gray-800 mb-1">Drag &amp; drop your file here</p>
        <p className="text-sm text-gray-500">
          or <span className="text-indigo-600 font-medium">browse files</span>
        </p>
        <input
          ref={inputRef}
          type="file"
          accept={ALLOWED.join(',')}
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        <div className="flex flex-wrap justify-center gap-2 mt-5">
          {['PDF', 'JPG', 'PNG', 'TIFF', 'WebP'].map((f) => (
            <span key={f} className="px-2.5 py-0.5 rounded-full bg-gray-100 text-gray-600 text-xs font-medium">{f}</span>
          ))}
          <span className="px-2.5 py-0.5 rounded-full bg-amber-100 text-amber-700 text-xs font-medium">Max {maxMb} MB</span>
        </div>
      </div>
    </div>
  );
}
