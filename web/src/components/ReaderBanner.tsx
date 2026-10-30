import Badge from './Badge';
import type { Health } from '../types';

interface Props {
  health: Health | null;
  /** The reader that produced the draft on screen, if any ("mock", "hosted", "custom"). */
  draftReader?: string | null;
}

/**
 * Always-visible banner on the intake screen (pilot Part 5).
 * It names the reader in use and says plainly where an uploaded photo goes.
 */
export default function ReaderBanner({ health, draftReader }: Props) {
  const d = health?.reader_detail;
  const status = health?.reader ?? 'not_built';
  const name = d?.name ?? (status === 'hosted' ? 'gemini_demo' : status);
  const thirdParty = d?.third_party ?? status === 'hosted';
  const down = status === 'down';

  let lead: string;
  let where: string;
  if (name === 'gemini_demo') {
    lead = `Reader in use: Google Gemini${d?.model ? ` (${d.model})` : ''}, demonstration only.`;
    where = 'Photos you upload here are sent to Google, a third party. Use synthetic pages only.';
  } else if (name === 'custom') {
    lead = `Reader in use: custom reader${d?.provider ? ` at ${d.provider}` : ''}.`;
    where = 'Photos you upload here are sent to that server, run for this centre.';
  } else if (name === 'mock') {
    lead = 'Reader in use: mock. It shows the same sample rows for any photo.';
    where = 'No photo leaves this server.';
  } else {
    lead = 'No reader is set up.';
    where = 'No photo leaves this server.';
  }

  return (
    <div
      className={`outcome-banner ${thirdParty ? 'outcome-error' : 'outcome-warning'}`}
      id="intake-privacy-banner"
      role="note"
      style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}
    >
      <span>
        <strong id="intake-reader-name">{lead}</strong>{' '}
        <span id="intake-reader-destination">{where}</span>{' '}
        {down && <strong id="intake-reader-down">The reader is off right now: type the rows beside the photo. </strong>}
        <span>
          <strong>Privacy Rule:</strong> Only synthetic pages, or pages with the phone column covered. No real register
          page may go to a hosted model.
        </span>
      </span>
      {(name === 'mock' || draftReader === 'mock') && <Badge name="reader: mock" id="intake-mock-badge" />}
    </div>
  );
}
