import sponsors from '@/config/sponsors';

interface SponsorPlaceholderProps {
  side: 'left' | 'right';
}

export const SponsorPlaceholder = ({ side }: SponsorPlaceholderProps) => {
  const items = sponsors.sideBanners[side];
  const heights = ['h-[250px]', 'h-[600px]', 'h-[250px]'];

  return (
    <div className="hidden lg:flex flex-col gap-4 justify-end">
      {items.map((sponsor, i) => (
        <a
          key={sponsor.id}
          href={sponsor.linkUrl}
          target="_blank"
          rel="noopener noreferrer"
          className={`w-[160px] ${heights[i] || 'h-[250px]'} rounded-xl overflow-hidden border-2 border-primary/20 bg-card/30 backdrop-blur-sm block group relative transition-transform hover:scale-[1.02]`}
        >
          <img
            src={sponsor.imageUrl}
            alt={sponsor.alt}
            className="w-full h-full object-cover"
            loading="lazy"
          />
          <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors" />
        </a>
      ))}
    </div>
  );
};
