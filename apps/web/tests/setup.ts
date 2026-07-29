// jsdom does not implement layout, so scrollIntoView is missing. Real browsers
// have it; stub it so component effects can run under test.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {};
}
