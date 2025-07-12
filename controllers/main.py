from odoo import http, _
import logging

_logger = logging.getLogger(__name__)


class SmsDeliveryReportController(http.Controller):
    @http.route("/sms/mtech/delivery", type="json", auth="none", csrf=False)
    def mtech_delivery_report(self, **kwargs):
        """
        Handles delivery report callbacks from MTech.
        MTech sends data in the request body as JSON.
        """
        _logger.info("Received MTech delivery report with data: %s", kwargs)

        message_id = kwargs.get("message_id")
        status = kwargs.get("status")

        if not message_id or not status:
            _logger.warning("MTech DLR missing message_id or status.")
            return "ERROR: Missing parameters"

        sms_record = (
            http.request.env["sms.sms"]
            .sudo()
            .search([("mtech_message_id", "=", message_id)], limit=1)
        )

        if sms_record:
            new_state = "error"  # Default to error
            if status.lower() == "delivered":
                new_state = "delivered"
            elif status.lower() in ["sent", "accepted"]:
                new_state = "sent"

            sms_record.write({"state": new_state})
            _logger.info("Updated SMS %s to state %s", message_id, new_state)
            return "OK"

        _logger.warning("Received DLR for unknown message_id: %s", message_id)
        return "ERROR: Message not found"
