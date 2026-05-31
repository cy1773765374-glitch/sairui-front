export function isWeComWebView(userAgent = window.navigator.userAgent): boolean {
  return /wxwork/i.test(userAgent)
}
