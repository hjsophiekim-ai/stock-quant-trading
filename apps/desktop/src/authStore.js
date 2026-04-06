const state = {
  accessToken: null,
  refreshToken: null,
  email: null,
};

function setAuth(next) {
  state.accessToken = next.accessToken ?? null;
  state.refreshToken = next.refreshToken ?? null;
  state.email = next.email ?? null;
}

function clearAuth() {
  state.accessToken = null;
  state.refreshToken = null;
  state.email = null;
}

function getAuth() {
  return { ...state };
}

module.exports = { setAuth, clearAuth, getAuth };
