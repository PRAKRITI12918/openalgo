/**
 * Ambient type definitions for realtime-feed frontend module.
 * Provides typing when loaded standalone without node_modules.
 */

declare module 'react' {
  export type FC<P = {}> = (props: P) => any
  export type ReactNode = any

  export function useCallback<T extends (...args: any[]) => any>(callback: T, deps: readonly any[]): T
  export function useEffect(effect: () => void | (() => void), deps?: readonly any[]): void
  export function useRef<T>(initialValue: T): { current: T }
  export function useRef<T = undefined>(): { current: T | undefined }
  export function useState<T>(initialState: T | (() => T)): [T, (newState: T | ((prevState: T) => T)) => void]
  export function useState<T = undefined>(): [T | undefined, (newState: T | undefined | ((prevState: T | undefined) => T | undefined)) => void]

  const React: {
    FC: FC<any>
    createElement: any
    [key: string]: any
  }
  export default React
}

declare global {
  namespace JSX {
    interface Element {}
    interface IntrinsicElements {
      [elemName: string]: any
    }
  }

  namespace NodeJS {
    type Timeout = any
  }
}

export {}
