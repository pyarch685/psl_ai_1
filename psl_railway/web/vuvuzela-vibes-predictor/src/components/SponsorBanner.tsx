import sponsors from '@/config/sponsors';

export const SponsorBanner = () => {
  const banner = sponsors.bottomBanner;

  return (
    <div className="w-full max-w-4xl mx-auto pt-6 relative z-10 flex-1 flex flex-col">
      {banner ? (
        <a
          href={banner.linkUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex-1 rounded-xl overflow-hidden border-2 border-primary/20 bg-card/30 backdrop-blur-sm block group relative min-h-[360px] transition-transform hover:scale-[1.01]"
        >
          <img
            src={banner.imageUrl}
            alt={banner.alt}
            className="w-full h-full object-cover"
            loading="lazy"
          />
          <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors" />
        </a>
      ) : (
        <div className="flex-1 border-2 border-dashed border-primary/20 rounded-xl bg-card/30 backdrop-blur-sm flex items-center justify-center gap-2 text-muted-foreground/50 min-h-[360px]">
          <span className="text-xs font-display uppercase tracking-wider">Sponsor Banner</span>
          <span className="text-[10px]">728 × 360</span>
        </div>
      )}
    </div>
  );
};
