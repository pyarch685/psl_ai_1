import { useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Loader2 } from 'lucide-react';
import { StadiumCard } from './StadiumCard';

interface ContentModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  fetchContent: () => Promise<string>;
}

// Helper function to format text content with markdown-like styling
const formatTextContent = (text: string): React.ReactNode => {
  const lines = text.split('\n');
  const formatted: React.ReactNode[] = [];
  let currentParagraph: string[] = [];
  let inList = false;

  lines.forEach((line, index) => {
    const trimmed = line.trim();
    
    // Empty line - end current paragraph or list
    if (!trimmed) {
      if (currentParagraph.length > 0) {
        formatted.push(
          <p key={`p-${index}`} className="mb-4 text-muted-foreground leading-relaxed">
            {currentParagraph.join(' ')}
          </p>
        );
        currentParagraph = [];
      }
      if (inList) {
        inList = false;
      }
      return;
    }

    // Title/Header (all caps with === or ---)
    if (trimmed.match(/^={3,}$|^-{3,}$/)) {
      return; // Skip separator lines
    }

    // Section header (all caps, no colon, length > 3)
    if (trimmed === trimmed.toUpperCase() && 
        trimmed.length > 3 && 
        !trimmed.includes(':') &&
        !trimmed.match(/^[A-Z\s]+$/)) {
      if (currentParagraph.length > 0) {
        formatted.push(
          <p key={`p-${index}`} className="mb-4 text-muted-foreground leading-relaxed">
            {currentParagraph.join(' ')}
          </p>
        );
        currentParagraph = [];
      }
      formatted.push(
        <h3 key={`h3-${index}`} className="mt-8 mb-4 font-display text-xl text-secondary font-bold border-b-2 border-primary/30 pb-2">
          {trimmed}
        </h3>
      );
      return;
    }

    // Separator line (=== or ---)
    if (trimmed.match(/^={3,}$|^-{3,}$/)) {
      if (currentParagraph.length > 0) {
        formatted.push(
          <p key={`p-${index}`} className="mb-4 text-muted-foreground leading-relaxed">
            {currentParagraph.join(' ')}
          </p>
        );
        currentParagraph = [];
      }
      formatted.push(
        <div key={`sep-${index}`} className="my-6 border-t-2 border-primary/20" />
      );
      return;
    }

    // Bullet points or list items
    if (trimmed.startsWith('-') || trimmed.startsWith('•')) {
      if (currentParagraph.length > 0) {
        formatted.push(
          <p key={`p-${index}`} className="mb-4 text-muted-foreground leading-relaxed">
            {currentParagraph.join(' ')}
          </p>
        );
        currentParagraph = [];
      }
      const listItem = trimmed.substring(1).trim();
      formatted.push(
        <div key={`li-${index}`} className="ml-6 mb-2 text-muted-foreground leading-relaxed flex items-start">
          <span className="text-secondary mr-2 mt-1">•</span>
          <span>{listItem}</span>
        </div>
      );
      return;
    }

    // Label: Value format (for contact details)
    if (trimmed.includes(':') && trimmed.split(':').length === 2) {
      if (currentParagraph.length > 0) {
        formatted.push(
          <p key={`p-${index}`} className="mb-4 text-muted-foreground leading-relaxed">
            {currentParagraph.join(' ')}
          </p>
        );
        currentParagraph = [];
      }
      const [label, value] = trimmed.split(':').map(s => s.trim());
      formatted.push(
        <div key={`kv-${index}`} className="mb-3">
          <span className="text-foreground font-semibold text-base">{label}:</span>{' '}
          {label.toLowerCase() === 'email' ? (
            <a href={`mailto:${value}`} className="text-secondary hover:underline">
              {value}
            </a>
          ) : label.toLowerCase() === 'telephone' ? (
            <a href={`tel:${value}`} className="text-secondary hover:underline">
              {value}
            </a>
          ) : (
            <span className="text-muted-foreground">{value}</span>
          )}
        </div>
      );
      return;
    }

    // Regular text line
    currentParagraph.push(trimmed);
  });

  // Add remaining paragraph
  if (currentParagraph.length > 0) {
    formatted.push(
      <p key="p-final" className="mb-4 text-muted-foreground leading-relaxed">
        {currentParagraph.join(' ')}
      </p>
    );
  }

  return <div className="space-y-2">{formatted}</div>;
};

export const ContentModal = ({ open, onOpenChange, title, fetchContent }: ContentModalProps) => {
  const [content, setContent] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setLoading(true);
      setError(null);
      fetchContent()
        .then((text) => {
          setContent(text);
          setLoading(false);
        })
        .catch((err) => {
          setError(err.message || 'Failed to load content');
          setLoading(false);
        });
    }
  }, [open, fetchContent]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card border-primary/30 max-w-4xl max-h-[90vh]">
        <DialogHeader>
          <DialogTitle className="font-display text-secondary text-2xl flex items-center gap-2">
            <span className="text-2xl">📄</span>
            {title}
          </DialogTitle>
        </DialogHeader>
        
        <ScrollArea className="max-h-[70vh] pr-4">
          {loading && (
            <div className="flex justify-center items-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-secondary" />
            </div>
          )}
          
          {error && (
            <div className="text-center py-8">
              <p className="text-destructive mb-2">⚠️ {error}</p>
              <p className="text-sm text-muted-foreground">
                Please try again later or contact support.
              </p>
            </div>
          )}
          
          {!loading && !error && (
            <div className="prose prose-invert max-w-none">
              <div className="text-foreground">
                {formatTextContent(content)}
              </div>
            </div>
          )}
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
};

