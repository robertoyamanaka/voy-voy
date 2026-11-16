# voyvoy.sh

The VoyVoy landing page. Next.js, exported as static files.

```bash
npm install
npm run dev          # http://localhost:3000
npm run build        # writes out/
npx wrangler deploy  # publishes out/ to Cloudflare (Workers static assets)
```

- Links that change at launch (GitHub repo, version) live in `src/lib/site.ts`.
- The pigeon and the VOYVOY wordmark are pixel art in `src/lib/sprites.ts`.
- Colors and type are tokens at the top of `src/app/globals.css`: red is the talker, blue is the reasoner.
- This is only the public landing page.
