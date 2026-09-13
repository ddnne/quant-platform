export {
  PilotReadyPublicationService,
  PremiumReceiptAuditEvidenceService,
  PremiumReceiptOperatorService,
  PremiumReceiptProductInputService,
} from "../src/index";

export default {
  fetch(): Response {
    return new Response(null, { status: 404 });
  },
};
