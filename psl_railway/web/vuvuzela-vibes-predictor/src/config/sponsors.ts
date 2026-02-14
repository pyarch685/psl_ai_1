// Sponsor Configuration
// Edit this file to add, remove, or update sponsors.
// Images can be URLs or imported assets.

export interface Sponsor {
  id: string;
  name: string;
  imageUrl: string;
  linkUrl: string;
  alt: string;
}

export interface SponsorConfig {
  sideBanners: {
    left: Sponsor[];
    right: Sponsor[];
  };
  bottomBanner: Sponsor | null;
}

// ──────────────────────────────────────────────
// EDIT SPONSORS BELOW
// ──────────────────────────────────────────────

const sponsors: SponsorConfig = {
  sideBanners: {
    left: [
      {
        id: 'left-1',
        name: 'Betway',
        imageUrl: 'https://placehold.co/160x250/1a1a2e/e0a526?text=Betway%0ASponsor&font=montserrat',
        linkUrl: 'https://example.com/betway',
        alt: 'Betway - Official Betting Partner',
      },
      {
        id: 'left-2',
        name: 'Castle Lager',
        imageUrl: 'https://placehold.co/160x600/0d5016/f5c518?text=Castle%0ALager%0APSL%0ASponsor&font=montserrat',
        linkUrl: 'https://example.com/castle',
        alt: 'Castle Lager - PSL Sponsor',
      },
      {
        id: 'left-3',
        name: 'Nike',
        imageUrl: 'https://placehold.co/160x250/111111/ffffff?text=Nike%0AJust+Do+It&font=montserrat',
        linkUrl: 'https://example.com/nike',
        alt: 'Nike - Just Do It',
      },
    ],
    right: [
      {
        id: 'right-1',
        name: 'MTN',
        imageUrl: 'https://placehold.co/160x250/ffcb05/000000?text=MTN%0AEverywhere%0AYou+Go&font=montserrat',
        linkUrl: 'https://example.com/mtn',
        alt: 'MTN - Everywhere You Go',
      },
      {
        id: 'right-2',
        name: 'DStv',
        imageUrl: 'https://placehold.co/160x600/002b5c/00a0e3?text=DStv%0APremier%0ALeague%0ALive&font=montserrat',
        linkUrl: 'https://example.com/dstv',
        alt: 'DStv - Watch PSL Live',
      },
      {
        id: 'right-3',
        name: 'Vodacom',
        imageUrl: 'https://placehold.co/160x250/e60000/ffffff?text=Vodacom%0AConnect&font=montserrat',
        linkUrl: 'https://example.com/vodacom',
        alt: 'Vodacom - Stay Connected',
      },
    ],
  },
  bottomBanner: {
    id: 'bottom-1',
    name: 'Hollywoodbets',
    imageUrl: 'https://placehold.co/728x360/4b0082/ffd700?text=Hollywoodbets%0AOfficial+PSL+Partner&font=montserrat',
    linkUrl: 'https://example.com/hollywoodbets',
    alt: 'Hollywoodbets - Official PSL Partner',
  },
};

export default sponsors;
