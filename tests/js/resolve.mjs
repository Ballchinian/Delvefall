//node's half of the importmap in base.html.
//
//the browser modules import each other by bare name ("dom", "decks"), which
//only works because base.html emits an importmap pointing each one at its
//content hashed url. node has no importmap, so without this every one of them
//is an unresolvable specifier and none can be imported by a test.
//
//the four names here are THE FOUR IN THAT MAP and have to stay in step with it.
//a new bare name added to base.html and not added here is a module the tests
//cannot load, which shows up as a loud failure rather than a silent gap.

import { pathToFileURL } from "node:url";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const JS = join(dirname(dirname(dirname(fileURLToPath(import.meta.url)))), "web", "static", "js");

const MAP = {
    dom: "dom.js",
    decks: "decks.js",
    report: "report.js",
    changes: "changes.js",
};

//format is not optional here. these are .js files in a tree with no
//package.json saying "type": "module", so node reads them as commonjs and the
//first export line is a syntax error. the browser knows they are modules
//because the script tag says so; this is where node is told the same thing,
//and it beats dropping a package.json into the folder railway deploys
export function resolve(specifier, context, next) {
    const file = MAP[specifier];
    if (file) {
        return {
            url: pathToFileURL(join(JS, file)).href,
            format: "module",
            shortCircuit: true,
        };
    }
    return next(specifier, context);
}
