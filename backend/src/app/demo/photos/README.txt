Photos for the seeded demo listings, named {listing_key}-{n}.jpg (keys are the "key" fields
in ../seed_data.json; n starts at 1 and the first photo is the thumbnail). They are the
project owner's own listing photos. A listing's "images" count in the seed must match its
photos here; a missing photo falls back to a generated placeholder (see ../images.py).

avatars/{user_key}.(jpg|png|webp|gif) become seeded users' profile pictures. Keep files
under 500 KB (the pre-commit large-file limit); shrink animated GIFs with ffmpeg.
