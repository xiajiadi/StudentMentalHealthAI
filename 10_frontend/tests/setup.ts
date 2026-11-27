/* global EventTarget */
window.scrollTo = () => undefined
Element.prototype.scrollIntoView = () => undefined

// jsdom has no media-query engine. Component tests use the default desktop state.
if (!window.matchMedia) {
  window.matchMedia = (media) => Object.assign(new EventTarget(), {
    media,
    matches: false,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
  })
}
