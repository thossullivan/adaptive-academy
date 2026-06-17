import { describe, expect, it } from 'vitest';
import { canShip } from './ship';

describe('canShip', () => {
  it('blocks when both url and content are empty', () => {
    expect(canShip('', '')).toBe(false);
    expect(canShip('   ', '  \n ')).toBe(false);
  });

  it('allows a paste with no url (the v1 path)', () => {
    expect(canShip('', 'def attn(): ...')).toBe(true);
  });

  it('allows a url with no paste (server fetches the content)', () => {
    expect(canShip('https://github.com/me/proj', '')).toBe(true);
  });
});
