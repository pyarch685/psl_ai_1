import { useState } from 'react';
import { ContentModal } from './ContentModal';
import { getAboutContent, getDisclaimerContent, getContactContent } from '@/lib/api';

type ModalType = 'about' | 'contact' | 'disclaimer' | null;

export const Footer = () => {
  const [openModal, setOpenModal] = useState<ModalType>(null);

  const currentYear = new Date().getFullYear();

  return (
    <>
      <footer className="relative z-10 border-t border-primary/20 bg-card/30 backdrop-blur-sm mt-12">
        <div className="container mx-auto px-4 py-8">
          <div className="flex flex-col md:flex-row items-center justify-between gap-4">
            <p className="text-muted-foreground text-sm">
              © {currentYear} Virtualsite Pty Ltd. All rights reserved.
            </p>
            
            <nav className="flex items-center gap-6">
              <button
                onClick={() => setOpenModal('about')}
                className="text-sm text-muted-foreground hover:text-secondary transition-colors font-medium"
              >
                About
              </button>
              <button
                onClick={() => setOpenModal('contact')}
                className="text-sm text-muted-foreground hover:text-secondary transition-colors font-medium"
              >
                Contact
              </button>
              <button
                onClick={() => setOpenModal('disclaimer')}
                className="text-sm text-muted-foreground hover:text-secondary transition-colors font-medium"
              >
                Disclaimer
              </button>
            </nav>
          </div>
          
          <p className="text-center text-muted-foreground text-sm mt-4 font-display">
            🇿🇦 Made with ❤️ in Mzansi ⚽
          </p>
        </div>
      </footer>

      <ContentModal
        open={openModal === 'about'}
        onOpenChange={(open) => setOpenModal(open ? 'about' : null)}
        title="About the Soccer Predictor"
        fetchContent={getAboutContent}
      />

      <ContentModal
        open={openModal === 'contact'}
        onOpenChange={(open) => setOpenModal(open ? 'contact' : null)}
        title="Contact Details"
        fetchContent={getContactContent}
      />

      <ContentModal
        open={openModal === 'disclaimer'}
        onOpenChange={(open) => setOpenModal(open ? 'disclaimer' : null)}
        title="Disclaimer Notice"
        fetchContent={getDisclaimerContent}
      />
    </>
  );
};
