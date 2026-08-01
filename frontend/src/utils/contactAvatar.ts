interface ContactAvatarLike {
  name?: string | null;
  phone?: string | null;
  photo?: string | null;
}

const LOCAL_PROFILE_PICTURE_PREFIX = '/media/profile-pictures/';
const CONTACT_AVATAR_CACHE_VERSION = '2';

const withContactAvatarCacheVersion = (photo: string): string => {
  if (!photo.startsWith(LOCAL_PROFILE_PICTURE_PREFIX)) {
    return photo;
  }

  try {
    const url = new URL(photo, 'https://local.invalid');
    url.searchParams.set('avatar_v', CONTACT_AVATAR_CACHE_VERSION);
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    const hashIndex = photo.indexOf('#');
    const base = hashIndex === -1 ? photo : photo.slice(0, hashIndex);
    const hash = hashIndex === -1 ? '' : photo.slice(hashIndex);
    const separator = base.includes('?') ? '&' : '?';
    return `${base}${separator}avatar_v=${CONTACT_AVATAR_CACHE_VERSION}${hash}`;
  }
};

export const resolveContactProfilePhoto = (contact?: ContactAvatarLike | null): string => {
  const photo = contact?.photo?.trim();
  if (!photo) return '';

  const normalized = photo.toLowerCase();
  if (normalized === 'null' || normalized === 'undefined' || normalized === 'none') {
    return '';
  }

  if (normalized.includes('ui-avatars.com/api')) {
    return '';
  }

  return withContactAvatarCacheVersion(photo);
};

export const getContactInitials = (nameOrPhone?: string | null): string => {
  const value = (nameOrPhone || '').trim();
  if (!value) return 'CT';

  if (value.startsWith('+') || /^\d+$/.test(value.substring(0, 2))) {
    return 'CT';
  }

  const parts = value.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return 'CT';
  if (parts.length === 1) return parts[0].substring(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};
