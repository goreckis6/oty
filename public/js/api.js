(function () {
  const cfg = () => window.YTS_CONFIG || { apiBase: "/api/v1" };

  function apiUrl(path, params) {
    const base = cfg().apiBase.replace(/\/$/, "");
    const full = `${base}${path}`;
    const url = full.startsWith("http")
      ? new URL(full)
      : new URL(full, window.location.origin);
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== "" && v !== "All") {
          url.searchParams.set(k, String(v));
        }
      });
    }
    return url.toString();
  }

  async function request(path, params) {
    const res = await fetch(apiUrl(path, params));
    const json = await res.json();
    if (!res.ok || json.status === "error") {
      throw new Error(json.status_message || `API error (${res.status})`);
    }
    return json.data;
  }

  window.YtsApi = {
    listMovies(params = {}) {
      return request("/list_movies.json", {
        limit: params.limit || 20,
        page: params.page || 1,
        quality: params.quality,
        minimum_rating: params.minimum_rating,
        query_term: params.query_term,
        genre: params.genre,
        sort_by: params.sort_by || "date_added",
        order_by: params.order_by || "desc",
        with_rt_ratings: params.with_rt_ratings ? "true" : undefined,
      });
    },

    movieDetails(movieId) {
      return request("/movie_details.json", {
        movie_id: movieId,
        with_images: "true",
        with_cast: "true",
      });
    },

    listUpcoming() {
      return request("/list_upcoming.json");
    },

    movieSuggestions(movieId) {
      return request("/movie_suggestions.json", { movie_id: movieId });
    },

    buildMagnet(torrent, title) {
      if (torrent.magnet_url) return torrent.magnet_url;
      const hash = torrent.hash;
      if (!hash) return torrent.url || "#";
      const dn = encodeURIComponent(title || "movie");
      const trackers = (cfg().trackers || []).map(
        (tr) => `&tr=${encodeURIComponent(tr)}`
      );
      return `magnet:?xt=urn:btih:${hash}&dn=${dn}${trackers.join("")}`;
    },
  };
})();
