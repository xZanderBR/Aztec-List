Real photos for the seeded demo listings, named {listing_key}-{n}.jpg (keys are the "key"
fields in ../seed_data.json; n starts at 1 and the first photo is the thumbnail). A
listing's "images" count in the seed must match its photos here; a missing photo falls back
to a generated placeholder (see ../images.py).

Two kinds of photo live here:
- The project owner's own photos, taken for the listings they wrote.
- Openly licensed stand-ins (public domain, CC0 or CC BY), resized to fit 815x910. Each one
  has an attribution record in credits.json, which the API serves at
  GET /api/v1/demo/credits and the frontend shows at /credits. Add a record for any new
  photo that isn't the owner's.

avatars/{user_key}.(jpg|png|webp|gif) become seeded users' profile pictures. Keep files
under 500 KB (the pre-commit large-file limit); shrink animated GIFs with ffmpeg.
