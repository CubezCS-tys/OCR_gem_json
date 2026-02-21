'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { 
  Upload, 
  FolderOpen, 
  FileText, 
  CheckCircle2,
  Clock,
  AlertCircle
} from 'lucide-react';
import { toast } from 'sonner';

interface PDF {
  name: string;
  path: string;
  size: number;
  size_mb: number;
  modified: string;
}

export default function JobsPanel() {
  const [pdfs, setPdfs] = useState<PDF[]>([]);
  const [selectedPdf, setSelectedPdf] = useState('');
  const [batchDirectory, setBatchDirectory] = useState('/home/yassine/OCR_gem_json/pdfs');
  const [outputDir, setOutputDir] = useState('./outputs');
  const [priority, setPriority] = useState('normal');
  const [format, setFormat] = useState('both');
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const fetchPdfs = async () => {
    setLoading(true);
    try {
      const response = await fetch('http://localhost:8000/api/pdfs');
      const data = await response.json();
      setPdfs(data.pdfs || []);
    } catch (error) {
      console.error('Failed to fetch PDFs:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPdfs();
  }, []);

  const handleSubmitSingle = async () => {
    if (!selectedPdf) {
      toast.error('Please select a PDF');
      return;
    }

    setSubmitting(true);
    try {
      const response = await fetch('http://localhost:8000/api/jobs/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pdf_path: selectedPdf,
          output_dir: outputDir,
          priority: priority,
          format: format,
          extract_images: true
        })
      });

      const data = await response.json();
      
      if (response.ok) {
        if (data.status === 'cached') {
          toast.info('Result already cached - no processing needed');
        } else {
          toast.success(`Job submitted: ${data.task_id}`);
        }
      } else {
        toast.error(`Failed to submit job: ${data.detail}`);
      }
    } catch (error) {
      toast.error('Failed to submit job');
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmitBatch = async () => {
    if (!batchDirectory) {
      toast.error('Please specify a directory');
      return;
    }

    setSubmitting(true);
    try {
      const response = await fetch('http://localhost:8000/api/jobs/submit-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          directory: batchDirectory,
          output_dir: outputDir,
          priority: priority,
          pattern: '*.pdf'
        })
      });

      const data = await response.json();
      
      if (response.ok) {
        toast.success(
          `Batch submitted: ${data.submitted} new, ${data.cached} cached (${data.total} total)`
        );
      } else {
        toast.error(`Failed to submit batch: ${data.detail}`);
      }
    } catch (error) {
      toast.error('Failed to submit batch');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Single Job Submission */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Upload className="h-5 w-5" />
            Submit Single Job
          </CardTitle>
          <CardDescription>
            Process a single PDF file
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div>
              <Label htmlFor="pdf-select">Select PDF</Label>
              <Select value={selectedPdf} onValueChange={setSelectedPdf}>
                <SelectTrigger id="pdf-select" className="mt-1">
                  <SelectValue placeholder="Choose a PDF..." />
                </SelectTrigger>
                <SelectContent>
                  {pdfs.map((pdf) => (
                    <SelectItem key={pdf.path} value={pdf.path}>
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4" />
                        <span>{pdf.name}</span>
                        <span className="text-xs text-gray-400">({pdf.size_mb} MB)</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <Label htmlFor="priority">Priority</Label>
                <Select value={priority} onValueChange={setPriority}>
                  <SelectTrigger id="priority" className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="low">Low</SelectItem>
                    <SelectItem value="normal">Normal</SelectItem>
                    <SelectItem value="high">High</SelectItem>
                    <SelectItem value="urgent">Urgent</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div>
                <Label htmlFor="format">Output Format</Label>
                <Select value={format} onValueChange={setFormat}>
                  <SelectTrigger id="format" className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="html">HTML Only</SelectItem>
                    <SelectItem value="json">JSON Only</SelectItem>
                    <SelectItem value="both">Both (HTML + JSON)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div>
                <Label htmlFor="output-dir-single">Output Directory</Label>
                <Input
                  id="output-dir-single"
                  value={outputDir}
                  onChange={(e) => setOutputDir(e.target.value)}
                  className="mt-1"
                />
              </div>
            </div>

            <Button
              onClick={handleSubmitSingle}
              disabled={!selectedPdf || submitting}
              className="w-full"
            >
              {submitting ? (
                <>
                  <Clock className="h-4 w-4 mr-2 animate-spin" />
                  Submitting...
                </>
              ) : (
                <>
                  <Upload className="h-4 w-4 mr-2" />
                  Submit Job
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Batch Job Submission */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FolderOpen className="h-5 w-5" />
            Submit Batch Jobs
          </CardTitle>
          <CardDescription>
            Process all PDFs in a directory
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div>
              <Label htmlFor="batch-dir">Directory Path</Label>
              <Input
                id="batch-dir"
                value={batchDirectory}
                onChange={(e) => setBatchDirectory(e.target.value)}
                className="mt-1"
                placeholder="/path/to/pdfs"
              />
              <p className="text-xs text-gray-500 mt-1">
                All *.pdf files in this directory will be processed
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="batch-priority">Priority</Label>
                <Select value={priority} onValueChange={setPriority}>
                  <SelectTrigger id="batch-priority" className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="low">Low</SelectItem>
                    <SelectItem value="normal">Normal</SelectItem>
                    <SelectItem value="high">High</SelectItem>
                    <SelectItem value="urgent">Urgent</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div>
                <Label htmlFor="output-dir-batch">Output Directory</Label>
                <Input
                  id="output-dir-batch"
                  value={outputDir}
                  onChange={(e) => setOutputDir(e.target.value)}
                  className="mt-1"
                />
              </div>
            </div>

            <Button
              onClick={handleSubmitBatch}
              disabled={!batchDirectory || submitting}
              className="w-full"
              variant="secondary"
            >
              {submitting ? (
                <>
                  <Clock className="h-4 w-4 mr-2 animate-spin" />
                  Submitting Batch...
                </>
              ) : (
                <>
                  <FolderOpen className="h-4 w-4 mr-2" />
                  Submit Batch
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Available PDFs List */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Available PDFs ({pdfs.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <Clock className="h-5 w-5 animate-spin text-gray-400" />
            </div>
          ) : pdfs.length === 0 ? (
            <div className="text-center py-4 text-sm text-gray-500">
              <AlertCircle className="h-8 w-8 mx-auto mb-2 text-gray-300" />
              No PDFs found in the pdfs directory
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {pdfs.slice(0, 10).map((pdf) => (
                <div
                  key={pdf.path}
                  className="flex items-center justify-between p-2 border rounded text-sm bg-slate-50 dark:bg-slate-900"
                >
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <FileText className="h-4 w-4 flex-shrink-0 text-blue-500" />
                    <span className="truncate">{pdf.name}</span>
                  </div>
                  <Badge variant="outline" className="text-xs flex-shrink-0 ml-2">
                    {pdf.size_mb} MB
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
