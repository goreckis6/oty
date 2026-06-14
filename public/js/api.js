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
    const ctype = res.headers.get("content-type") || "";
    if (ctype.includes("text/html")) {
      throw new Error("API returned HTML instead of JSON (check reverse proxy /api/v1)");
    }
    let json = {};
    try {
      json = await res.json();
    } catch {
      json = {};
    }
    if (!res.ok || json.status === "error") {
      const detail = json.detail;
      const msg =
        (typeof detail === "string" && detail) ||
        json.status_message ||
        (res.headers.get("content-type")?.includes("text/html")
          ? "API returned HTML instead of JSON (check reverse proxy /api/v1)"
          : `API error (${res.status})`);
      const err = new Error(msg);
      err.status = res.status;
      throw err;
    }
    if (!json.data) {
      throw new Error("API response missing data");
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

    movieDetails(idOrSlug) {
      const params = { with_images: "true", with_cast: "true" };
      if (/^\d+$/.test(String(idOrSlug))) {
        params.movie_id = idOrSlug;
      } else {
        params.slug = idOrSlug;
      }
      return request("/movie_details.json", params);
    },

    listUpcoming() {
      return request("/list_upcoming.json");
    },

    movieSuggestions(idOrSlug) {
      const params = {};
      if (/^\d+$/.test(String(idOrSlug))) {
        params.movie_id = idOrSlug;
      } else {
        params.slug = idOrSlug;
      }
      return request("/movie_suggestions.json", params);
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
