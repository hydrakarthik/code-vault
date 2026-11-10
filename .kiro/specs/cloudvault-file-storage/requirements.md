# Requirements Document

## Introduction

CloudVault is a multi-user Flask web application for storing files privately. Users register and sign in with an email and password, then upload, list, view, download, and delete their own files through a responsive dashboard. Each user can access only the files under that user's own storage prefix.

The stack is Supabase, GitHub, and Vercel only. Supabase Auth authenticates users (email confirmation required) and a private Supabase Storage bucket protected by Row Level Security stores files. Source code lives in GitHub and is deployed by Vercel through its Git integration. Because Vercel limits request bodies to about 4.5 MB, the browser uploads files directly to Supabase Storage through a signed upload URL issued by CloudVault after server-side validation. Local development runs `python run.py` against the developer's own Supabase project. The implementation creates no Supabase resources, pushes nothing to GitHub, and deploys nothing to Vercel without user approval.

## Glossary

- **CloudVault**: The Flask web application, including the backend API and the browser-based dashboard.
- **Dashboard**: The responsive HTML, CSS, and JavaScript user interface served by CloudVault.
- **User**: A person with a registered account, identified by a User_ID and an email address.
- **User_ID**: The Supabase Auth user id of a User.
- **Supabase_Auth**: The Supabase Auth service used with email and password.
- **Email_Confirmation**: The Supabase Auth step in which a newly registered User confirms ownership of the email address through a link sent by email.
- **Unconfirmed_User**: A User who has registered but has not completed Email_Confirmation.
- **Session**: A Flask server-signed cookie session holding the Auth_Tokens, User_ID, email, and CSRF_Token of a signed-in User.
- **Auth_Tokens**: The Supabase access token and refresh token of a User.
- **SECRET_KEY**: The environment variable holding the key used to sign Sessions.
- **CSRF_Token**: A per-session random token that CloudVault requires on state-changing requests.
- **Bucket**: The private Supabase Storage bucket named by SUPABASE_BUCKET.
- **Object_Key**: The storage path of a file, in the form `<User_ID>/<Secure_Filename>`.
- **RLS_Policy**: A Supabase Row Level Security policy on `storage.objects` that restricts access to objects whose first path segment equals `auth.uid()`.
- **Anon_Key**: The Supabase public anon API key, supplied in SUPABASE_ANON_KEY.
- **Service_Role_Key**: The Supabase privileged API key that bypasses RLS_Policy.
- **Signed_Upload_URL**: A time-limited Supabase Storage URL, created with createSignedUploadUrl, that permits one upload to one Object_Key.
- **Signed_URL**: A time-limited Supabase Storage URL that grants read access to one object.
- **Allowed_Extensions**: The configurable list of permitted file extensions, defaulting to pdf, txt, docx, xlsx, csv, png, jpg, gif.
- **Previewable_Types**: The file extensions png, jpg, gif, pdf, txt, and csv.
- **Max_Upload_Size**: The configurable maximum file size in bytes, defaulting to 10 MB (10,485,760 bytes).
- **Secure_Filename**: A file name sanitized by the Werkzeug `secure_filename` function.
- **File_Record**: The metadata of a stored file consisting of name, size in bytes, and upload date.
- **Fake_Supabase**: A test double for the HTTP session used for Supabase calls, allowing tests to run offline.
- **Vercel_Entrypoint**: The `api/index.py` module that exposes the Flask application to Vercel, configured by `vercel.json`.
- **CI_Workflow**: The optional GitHub Actions workflow at `.github/workflows/ci.yml`.

## Requirements

### Requirement 1: User Registration

**User Story:** As a new user, I want to register with my email and password, so that I can have my own private file storage.

#### Acceptance Criteria

1. THE Dashboard SHALL provide a registration page containing email and password fields, reachable from a Register link on the login page.
2. WHEN a visitor submits a valid email and password on the registration page, THE CloudVault SHALL create the account through Supabase_Auth.
3. WHEN registration succeeds, THE CloudVault SHALL display a message instructing the visitor to check the email inbox to confirm the account and SHALL create no Session.
4. IF the submitted email is malformed or the password is shorter than 8 characters, THEN THE CloudVault SHALL reject the registration with HTTP status 400 and a message stating the violated rule.
5. IF the submitted email is already registered, THEN THE CloudVault SHALL display a generic message that does not reveal whether the email is registered.
6. IF Supabase_Auth fails during registration, THEN THE CloudVault SHALL display a generic error message and create no Session.

### Requirement 2: Login and Email Confirmation

**User Story:** As a registered user, I want to sign in with my email and password, so that I can access my files.

#### Acceptance Criteria

1. WHEN a confirmed User submits a matching email and password, THE CloudVault SHALL create a Session containing the Auth_Tokens, User_ID, and email, and redirect to the Dashboard.
2. IF the submitted email or password does not match a User, THEN THE CloudVault SHALL display a generic invalid-credentials message and create no Session.
3. IF an Unconfirmed_User submits a login, THEN THE CloudVault SHALL display a message stating that the email address must be confirmed before login and create no Session.
4. THE CloudVault SHALL set the Session cookie with the HttpOnly and SameSite=Lax attributes.
5. WHERE the deployment is production, THE CloudVault SHALL set the Session cookie with the Secure attribute.
6. THE Dashboard SHALL display the email of the signed-in User in the navigation bar.

### Requirement 3: Logout and Session Token Refresh

**User Story:** As a signed-in user, I want to log out and stay signed in while my session is valid, so that my account stays secure without frequent re-login.

#### Acceptance Criteria

1. WHEN a User selects logout, THE CloudVault SHALL revoke the Supabase session using the User access token, clear the Session, and redirect to the login page.
2. WHEN a request arrives with a Session whose access token has expired, THE CloudVault SHALL obtain new Auth_Tokens using the refresh token and store the new Auth_Tokens in the Session.
3. IF the refresh of the Auth_Tokens fails, THEN THE CloudVault SHALL clear the Session, reject browser page requests with a redirect to the login page, and reject API requests with HTTP status 401.

### Requirement 4: Access Control

**User Story:** As a user, I want every page and file operation to require sign-in, so that nobody can reach my files without authenticating.

#### Acceptance Criteria

1. IF a request for the Dashboard or a file operation arrives without a valid Session, THEN THE CloudVault SHALL reject browser page requests with a redirect to the login page and API requests with HTTP status 401.
2. WHEN a signed-in User requests the login or registration page, THE CloudVault SHALL redirect to the Dashboard.

### Requirement 5: CSRF Protection

**User Story:** As a user, I want state-changing requests protected against forged submissions, so that other sites cannot act on my behalf.

#### Acceptance Criteria

1. WHEN CloudVault renders a page containing a form or issuing state-changing requests, THE CloudVault SHALL provide the CSRF_Token of the visitor Session to the page.
2. IF a login, registration, logout, upload-URL, or delete request does not carry a CSRF_Token matching the Session CSRF_Token, THEN THE CloudVault SHALL reject the request with HTTP status 400 and perform no state change.
3. THE CloudVault SHALL compare submitted CSRF_Token values with the Session CSRF_Token using a constant-time comparison.

### Requirement 6: Configuration

**User Story:** As a developer, I want all configuration read from environment variables, so that local development and Vercel use the same mechanism.

#### Acceptance Criteria

1. THE CloudVault SHALL read SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_BUCKET, SECRET_KEY, ALLOWED_EXTENSIONS, and MAX_UPLOAD_SIZE from environment variables.
2. WHEN the developer runs `python run.py` with SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_BUCKET, and SECRET_KEY set in `.env`, THE CloudVault SHALL serve the Dashboard on localhost using the developer's Supabase project.
3. IF SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_BUCKET, or SECRET_KEY is not set at startup, THEN THE CloudVault SHALL terminate startup with an error message naming the missing variable.
4. THE CloudVault SHALL apply the defaults of pdf, txt, docx, xlsx, csv, png, jpg, gif and 10,485,760 bytes when ALLOWED_EXTENSIONS and MAX_UPLOAD_SIZE are not set.

### Requirement 7: Per-User Isolation

**User Story:** As a user, I want my files to be visible only to me, so that other users cannot see or change them.

#### Acceptance Criteria

1. THE CloudVault SHALL store each file under the Object_Key `<User_ID>/<Secure_Filename>`, with the User_ID taken from the Session and never from request input.
2. WHEN a User lists, downloads, views, or deletes files, THE CloudVault SHALL operate only on Object_Keys whose prefix equals the User_ID of that User.
3. THE CloudVault SHALL call Supabase Storage with the access token of the signed-in User so that the RLS_Policy applies to every storage call.
4. IF a User requests a file that exists only under another User_ID, THEN THE CloudVault SHALL return HTTP status 404.

### Requirement 8: Direct Upload with Progress

**User Story:** As a user, I want to upload files with visible progress even on Vercel, so that files up to 10 MB can be stored and I can see the transfer status.

#### Acceptance Criteria

1. WHEN a User submits the upload form, THE Dashboard SHALL send the file name and declared size to CloudVault to request a Signed_Upload_URL.
2. WHEN CloudVault receives an upload-URL request, THE CloudVault SHALL validate the file name, extension, and declared size, and create the Signed_Upload_URL for the Object_Key of that User using the User access token.
3. WHEN the Dashboard receives a Signed_Upload_URL, THE Dashboard SHALL send the file content directly to Supabase Storage with an XHR PUT request and display a progress indicator showing the percentage uploaded.
4. THE CloudVault SHALL accept no file content in upload-URL requests and SHALL limit the upload-URL request body to 4 KB.
5. IF the upload-URL request fails validation, THEN THE CloudVault SHALL return the status and error message defined in Requirement 9 and issue no Signed_Upload_URL.
6. IF the Supabase Storage PUT request fails, THEN THE Dashboard SHALL display an error message and hide the progress indicator.
7. WHEN the Supabase Storage PUT request succeeds, THE Dashboard SHALL display a success message and refresh the file list.
8. IF a file with the same Object_Key already exists, THEN THE CloudVault SHALL issue a Signed_Upload_URL that permits replacing the existing file.
9. IF the Secure_Filename of the declared file name is empty, THEN THE CloudVault SHALL reject the request with HTTP status 400 and an error message.

### Requirement 9: Upload Validation

**User Story:** As a user, I want uploads validated by type and size, so that only acceptable files are stored.

#### Acceptance Criteria

1. IF the extension of a declared file is not in Allowed_Extensions, THEN THE CloudVault SHALL reject the request with HTTP status 400 and an error message listing the allowed types.
2. IF the declared size exceeds Max_Upload_Size, THEN THE CloudVault SHALL reject the request with HTTP status 413 and an error message stating the maximum size.
3. IF the declared size is missing, not an integer, or less than 1, THEN THE CloudVault SHALL reject the request with HTTP status 400 and an error message.
4. THE CloudVault SHALL compare file extensions case-insensitively.
5. WHEN the Dashboard receives a selected file whose extension or size violates the rules, THE Dashboard SHALL display a validation message before sending any request.
6. THE README SHALL instruct the reader to set the Bucket file size limit to Max_Upload_Size so that Supabase Storage enforces the limit independently of CloudVault.

### Requirement 10: File Listing

**User Story:** As a user, I want to see my stored files, so that I can find and manage them.

#### Acceptance Criteria

1. WHEN a User opens the Dashboard, THE CloudVault SHALL display a table of the File_Records of that User containing name, size, and upload date.
2. THE Dashboard SHALL display file sizes in human-readable units (B, KB, MB).
3. THE Dashboard SHALL display upload dates in a consistent date and time format.
4. WHILE the User has no stored files, THE Dashboard SHALL display an empty-state message in place of the table rows.
5. THE CloudVault SHALL order File_Records by upload date, newest first.
6. IF Supabase Storage fails to list files, THEN THE CloudVault SHALL return HTTP status 502 and THE Dashboard SHALL display an error message.
7. THE Dashboard SHALL escape file names before rendering them in HTML.

### Requirement 11: File Download

**User Story:** As a user, I want to download my files securely, so that I can retrieve them without exposing the storage.

#### Acceptance Criteria

1. WHEN a User requests a download, THE CloudVault SHALL redirect to a Signed_URL that expires after 60 seconds and carries an attachment download disposition.
2. IF the requested file does not exist for that User, THEN THE CloudVault SHALL return HTTP status 404.
3. THE CloudVault SHALL require a valid Session for every download request.

### Requirement 12: File View

**User Story:** As a user, I want to open supported files in a new browser tab, so that I can preview them without downloading.

#### Acceptance Criteria

1. THE Dashboard SHALL display a View action for each File_Record that opens the file in a new browser tab.
2. WHERE the file extension is in Previewable_Types, WHEN a User selects View, THE CloudVault SHALL redirect to a Signed_URL that expires after 60 seconds and carries an inline disposition.
3. WHERE the file extension is not in Previewable_Types, THE Dashboard SHALL render the View action as disabled with a tooltip and visible label stating that preview is not available for the file type.
4. IF a view request names a file whose extension is not in Previewable_Types, THEN THE CloudVault SHALL return HTTP status 400.
5. IF the requested file does not exist for that User, THEN THE CloudVault SHALL return HTTP status 404.
6. THE CloudVault SHALL require a valid Session for every view request.

### Requirement 13: File Deletion

**User Story:** As a user, I want to delete my files, so that I can remove content I no longer need.

#### Acceptance Criteria

1. WHEN a User selects delete for a file, THE Dashboard SHALL request confirmation before sending the delete request.
2. WHEN a User confirms deletion of a file, THE CloudVault SHALL delete the file from Supabase Storage and THE Dashboard SHALL remove the file from the table.
3. IF the file to delete does not exist for that User, THEN THE CloudVault SHALL return HTTP status 404.
4. IF Supabase Storage fails to delete the file, THEN THE CloudVault SHALL return HTTP status 502 and THE Dashboard SHALL display an error message.

### Requirement 14: Secret Handling

**User Story:** As a security-conscious owner, I want secrets kept out of the browser, the code, and the repository, so that a leak cannot expose all user data.

#### Acceptance Criteria

1. THE CloudVault SHALL use the Anon_Key and the User access token for all Supabase calls and SHALL NOT read, use, or reference the Service_Role_Key.
2. THE CloudVault SHALL contain no Supabase keys, passwords, or tokens in source code, logs, error responses, or Dashboard pages, with the exception of the Anon_Key where the browser requires it.
3. THE CloudVault SHALL store the Auth_Tokens only in the signed Session cookie and SHALL NOT expose the refresh token to Dashboard JavaScript.
4. IF an unhandled error occurs while processing a request, THEN THE CloudVault SHALL log the error server-side and return a generic error response without stack traces or credentials.
5. THE CloudVault SHALL exclude `.env` files and the `.venv` directory from version control through a `.gitignore` file.
6. THE CloudVault SHALL include an `.env.example` file containing placeholder values for SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_BUCKET, and SECRET_KEY and no real secrets.

### Requirement 15: Vercel Deployment Support

**User Story:** As an owner, I want the application to be deployable to Vercel, so that I can host it in production.

#### Acceptance Criteria

1. THE CloudVault SHALL provide a `vercel.json` file that routes all requests to the Vercel_Entrypoint.
2. THE Vercel_Entrypoint SHALL expose the Flask application object created by the application factory.
3. THE CloudVault SHALL serve static assets in a way that works under the Vercel routing configuration.
4. THE CloudVault SHALL perform no writes to the local file system.

### Requirement 16: Responsive Dashboard

**User Story:** As a user, I want a clean, responsive dashboard, so that I can manage files on desktop and mobile.

#### Acceptance Criteria

1. THE Dashboard SHALL provide a login page, a registration page, a files page containing the upload control and file table, and a navigation bar containing the application name, the signed-in email, and a logout control.
2. WHILE the viewport width is 600 pixels or less, THE Dashboard SHALL adapt the layout so that the content fits without horizontal page scrolling.
3. THE Dashboard SHALL provide text labels for form controls and action buttons.
4. THE Dashboard SHALL display status and error messages in a region announced to assistive technologies through an ARIA live attribute.

### Requirement 17: GitHub and Vercel Git Integration

**User Story:** As an owner, I want my code in GitHub and deployed automatically by Vercel, so that every change to main reaches production and every pull request gets a preview.

#### Acceptance Criteria

1. THE README SHALL document creating a GitHub repository and pushing the project to the repository.
2. THE README SHALL document importing the GitHub repository into Vercel through the Vercel Git integration, with automatic production deployment on each push to the `main` branch and preview deployments for pull requests.
3. THE README SHALL document setting SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_BUCKET, and SECRET_KEY in the Vercel dashboard environment variables and not in the repository.
4. THE CloudVault SHALL provide a CI_Workflow that runs pytest on every push and pull request.
5. THE CI_Workflow SHALL require no repository secrets.
6. THE CloudVault SHALL NOT push to GitHub, create Supabase resources, or deploy to Vercel without approval from the user.

### Requirement 18: Documentation

**User Story:** As an owner, I want clear setup documentation, so that I can create the Supabase project, run the app locally, and deploy it myself.

#### Acceptance Criteria

1. THE README SHALL document Supabase project setup: enabling email and password sign-in, requiring Email_Confirmation, and configuring the site URL and redirect URLs for both localhost and the Vercel domain.
2. THE README SHALL document creating the Bucket as private, with a file size limit equal to Max_Upload_Size.
3. THE README SHALL contain SQL that creates RLS_Policy rules on `storage.objects` allowing a User to select, insert, update, and delete only objects in the Bucket whose first path segment equals `auth.uid()`.
4. THE README SHALL document the environment variables SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_BUCKET, SECRET_KEY, ALLOWED_EXTENSIONS, and MAX_UPLOAD_SIZE.
5. THE README SHALL document running the application locally with `python run.py` and running the automated tests.
6. THE README SHALL state that the Service_Role_Key must never be configured in CloudVault or exposed to the browser.
7. THE README SHALL state that the project creates no Supabase resources and runs no deployment commands.

### Requirement 19: Project Structure, Dependencies, and Tests

**User Story:** As a developer, I want a clean project structure, pinned dependencies, and offline tests, so that I can maintain the application with confidence.

#### Acceptance Criteria

1. THE CloudVault SHALL organize code into separate modules for application setup, configuration, authentication, routes, validation, and Supabase storage, with templates and static assets in separate directories.
2. THE CloudVault SHALL provide a `requirements.txt` file in which every dependency is pinned to an exact version.
3. THE CloudVault SHALL include automated tests covering registration, login, unconfirmed-user rejection, token refresh, per-user isolation, upload validation including the upload-URL endpoint, view and download behavior, and delete behavior.
4. THE automated tests SHALL run without network access by using a Fake_Supabase in place of the Supabase HTTP session.

### Requirement 20: File Metadata in Supabase PostgreSQL

**User Story:** As a user, I want my file metadata stored in Supabase PostgreSQL with Row Level Security, so that my file list is queryable, durable, and visible only to me.

#### Acceptance Criteria

1. THE `public.files` table SHALL store one row per user file with columns id (uuid primary key), user_id (uuid referencing auth.users, on delete cascade, default auth.uid()), name (text), size (bigint), content_type (text), object_key (text), created_at (timestamptz default now()), and updated_at (timestamptz), and SHALL enforce a unique constraint on (user_id, name).
2. THE `public.files` table SHALL have RLS enabled, with policies allowing select, insert, update, and delete for the authenticated role only where user_id equals auth.uid(), and SHALL grant the anon role no access.
3. WHEN the browser's direct upload to Supabase Storage succeeds, THE Dashboard SHALL send POST /api/files/complete with the file name and the CSRF_Token.
4. WHEN CloudVault receives POST /api/files/complete for a valid name, THE CloudVault SHALL verify that the object exists under the User's Storage prefix, read its size and content type from Supabase Storage, and upsert the row through PostgREST (/rest/v1/files) using the User access token.
5. IF the object does not exist under the User's Storage prefix, THEN THE CloudVault SHALL return HTTP status 404 and write no row.
6. THE CloudVault SHALL validate the name in POST /api/files/complete using the same rules as Requirement 9.
7. WHEN a User requests GET /api/files, THE CloudVault SHALL return the rows of the files table as name, size, and uploaded_at (created_at, or updated_at when the file was replaced), ordered newest first.
8. IF the database request fails during listing, THEN THE CloudVault SHALL return HTTP status 502.
9. WHEN a User deletes a file, THE CloudVault SHALL remove the Storage object and the files row.
10. IF neither the row nor the Storage object exists, THEN THE CloudVault SHALL return HTTP status 404.
11. IF the Storage object is missing but the row exists, THEN THE CloudVault SHALL delete the row and return HTTP status 200.
12. THE CloudVault SHALL continue to use Supabase Storage existence checks for view and download requests.
13. THE project SHALL ship `supabase/schema.sql` containing the table, index, RLS enablement, policies, updated_at trigger, and grants, and `supabase/storage.sql` containing an insert into storage.buckets creating a private bucket with file_size_limit 10485760 and on conflict do nothing, plus the four storage.objects RLS policies.
14. THE SQL files SHALL be idempotent, using `drop policy if exists` and `create table if not exists`.
15. THE README SHALL reference `supabase/schema.sql` and `supabase/storage.sql` for the database setup, in place of or in addition to inline SQL.
16. THE CloudVault SHALL use no database password and no Service_Role_Key and SHALL introduce no new environment variables.
17. THE automated tests SHALL extend Fake_Supabase with a /rest/v1/files endpoint emulating PostgREST and RLS.

### Requirement 21: Landing Page and Dark Glass Theme
**User Story:** As a visitor, I want a striking public landing page and a consistent dark glass look across the site, so that I understand what CloudVault offers and can sign up quickly.
#### Acceptance Criteria
1. WHEN a visitor without a Session requests `/`, THE CloudVault SHALL render a public landing page instead of redirecting to the login page; WHEN a signed-in User requests `/`, THE CloudVault SHALL render the Dashboard as before, including token refresh and redirect to the login page if refresh fails.
2. THE landing page SHALL contain the decorative "Cloud" headline (aria-hidden), an h1 title "Secure File Vault", a one-sentence description, a "Get Started" link to the registration page, and a "Sign in" link to the login page.
3. THE landing page SHALL build the hero art (orbs, grid, cloud, widget cards, connectors, cables, wave mesh) with HTML, CSS, inline SVG, and a canvas script, with no external images, fonts, or libraries, and SHALL mark the hero art aria-hidden.
4. WHILE the user has `prefers-reduced-motion: reduce`, THE landing page SHALL show no animation, with a static wave frame and no floating.
5. WHILE the viewport is 720 px wide or narrower, THE landing page SHALL stack the title and buttons, hide some widget cards, and avoid horizontal page scrolling.
6. THE login, registration, dashboard, and error pages SHALL use the same dark glass theme (near-black background, frosted cards, light primary button, blue accent) while keeping all existing element IDs, classes, form fields, link texts, and JavaScript behavior.
7. THE CloudVault pages SHALL keep visible focus outlines, SHALL keep text contrast of at least 4.5:1 against the background, and SHALL provide a "Skip to content" link.
8. THE navigation bar SHALL show "Sign in" and "Create account" links for visitors without a Session, and the existing email chip and logout control for signed-in Users; the brand SHALL link to `/`.

Reference style (described, not embedded): near-black background with a faint grid; large blurred blue spheres with a soft green-white sheen cut off along the top edge; a huge light-gray "Cloud" headline across the upper half; a glowing 3D blue cloud in the center with a curved wireframe grid; small frosted-glass widget cards floating around the cloud (toggle bars, a window with dots and a slider, a 2x3 icon grid, a list, a bar chart, a slider, server rows, stacked pills, a small square icon) joined to the cloud by thin right-angle lines; thin cables hanging under the cloud; an animated dotted perspective wave mesh across the bottom; a large white title at bottom-left; a light "Get Started" button at bottom-right.

### Requirement 22: Display Name Greeting
**User Story:** As a User, I want to see my name after I sign in, so that CloudVault feels personal and I can confirm which account I am using.
#### Acceptance Criteria
1. THE registration page SHALL provide an optional "Name" field (maximum 50 characters) before the email field.
2. WHEN a visitor registers with a non-empty name, THE CloudVault SHALL send the name to Supabase Auth as user metadata `display_name` (trimmed, internal whitespace collapsed, control characters removed).
3. IF the submitted name exceeds 50 characters after trimming, THEN THE CloudVault SHALL reject the registration with HTTP status 400 and the message "Name must be at most 50 characters."
4. WHEN a User signs in or the Session is refreshed, THE CloudVault SHALL store a display name in the Session: the `display_name` from Supabase user metadata if present and valid, otherwise the part of the email before "@".
5. THE Dashboard SHALL greet the User with a heading "Hi, <display name>" on the files page and SHALL show the display name in the navigation bar user chip, with the email as its title tooltip.
6. THE CloudVault SHALL HTML-escape the display name wherever rendered and SHALL take the display name from no request input other than the registration form.
