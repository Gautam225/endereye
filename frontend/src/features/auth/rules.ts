/** Same rule as the backend (app/schemas/auth.py): length is what makes a password strong. */
export const MIN_PASSWORD = 10;

export const PASSWORD_HINT = `At least ${MIN_PASSWORD} characters. A short sentence works well.`;
