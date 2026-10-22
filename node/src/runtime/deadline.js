"use strict";

// A hard deadline: a slow or hung cache must never hold a live call past its budget.

/** What within() resolves to when the deadline passed first. */
const LATE = Symbol("late");

/** `promise`'s result, or LATE once `ms` have passed; the timer never outlives the race. */
function within(ms, promise) {
  let timer;
  const late = new Promise((resolve) => {
    timer = setTimeout(() => resolve(LATE), ms);
  });
  return Promise.race([promise, late]).finally(() => clearTimeout(timer));
}

module.exports = { LATE, within };
