/*
 * Cloudflare's nodejs_compat runtime supplies these modules. Keep the local
 * declarations deliberately narrow so @types/node cannot redeclare Worker
 * Web Platform globals while dependency declarations remain type-checkable.
 */
declare module "node:http" {
  export interface IncomingMessage {}
  export interface ServerResponse {}
}

declare module "node:diagnostics_channel" {
  export interface Channel<Store = unknown, Context = unknown> {
    readonly __store?: Store;
    readonly __context?: Context;
  }
}

declare module "node:async_hooks" {
  export class AsyncLocalStorage<T> {
    getStore(): T | undefined;
    run<R>(store: T, callback: (...args: never[]) => R): R;
  }
}
