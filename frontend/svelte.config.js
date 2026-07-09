import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
export default {
  kit: {
    // Pure SPA: no prerendering, one index.html fallback for all client routes.
    // FastAPI serves this build in the container (see Dockerfile).
    adapter: adapter({ fallback: 'index.html' })
  }
};
