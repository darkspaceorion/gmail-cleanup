"""Every word Jev sees lives here, so the wording is easy to read, audit and tweak.

Jev only judges. decide.py turns the answers into Keep / Delete / Review.
Two sets: one per sender (judged from a sample of their emails), and one per single email,
used only for mixed senders (shops that send receipts AND adverts).
"""

# The category options. Option names are sent to Jev, so they describe the content.
CATEGORIES = {
    "marketing_newsletter": "Adverts, sales, promotions, newsletters or digests sent to many people",
    "receipt_order": "Order confirmations, receipts or invoices for something the user bought",
    "bank_bill_statement": "Bank, card, loan, utility or tax statements, bills and payment notices",
    "one_time_code": "A one-time code or link used once to log in or verify an address",
    "account_security_alert": "Sign-in alerts, password resets, credit alerts or account setting changes",
    "social_notification": "Alerts from social media sites about likes, comments, follows or messages",
    "shipping_delivery": "Tracking updates about a parcel being shipped or delivered",
    "personal_from_a_person": "An email a friend, family member or acquaintance typed to the user",
    "work_business": "Emails about the user's job, clients or his own businesses",
    "travel_booking": "Flight, hotel, rental car or event ticket bookings and itineraries",
    "job_alert": "Automated job listings or job-match alerts sent to many people",
    "job_invitation": "A specific client, employer or recruiter inviting the user to interview, apply or talk",
    "government_legal_medical": "Government, legal, insurance or medical letters and records",
    "other": "Anything that fits none of the kinds above",
}

# Categories decide.py may recommend deleting (when nothing else says keep).
DELETABLE = {"marketing_newsletter", "social_notification", "shipping_delivery", "one_time_code", "job_alert"}
# The user's call (2026-11-03): old codes and job alerts go even when "record" is unsettled.
# Trial 2b showed he keeps account alerts (sign-ins, resets, credit), so those are not deletable.
LOOSE_DELETE = {"one_time_code", "job_alert"}

SENDER_QUESTIONS = {
    "category": {
        "type": "choice",
        "instructions": "Which kind of email does this sender mostly send the user, judging by `sample_emails`?",
        "criteria": CATEGORIES,
    },
    "written_by_person": {
        "type": "noul",
        "instructions": "Were the emails in `sample_emails` written personally to the user by a real person?",
        "criteria": {
            "true": "A friend, family member, colleague or client typed the email to the user",
            "false": "A company system or mailing list sent the email automatically",
        },
    },
    "record_worth_keeping": {
        "type": "noul",
        "instructions": "Might the user need any of the emails in `sample_emails` later as a record or proof?",
        "criteria": {
            "true": "Receipts, invoices, statements, contracts, bookings, warranties, medical, legal or tax papers",
            "false": "Adverts, newsletters, social media alerts, delivery tracking or one-time codes",
        },
    },
    "mixed_sender": {
        "type": "noul",
        "instructions": "Does `sample_emails` contain both records worth keeping and adverts from this sender?",
        "criteria": {
            "true": "A shop that sends order receipts as well as sales promotions",
            "false": "All the emails are the same kind",
        },
    },
}

EMAIL_QUESTIONS = {
    "category": {
        "type": "choice",
        "instructions": "Which kind of email is `email`?",
        "criteria": CATEGORIES,
    },
    "written_by_person": {
        "type": "noul",
        "instructions": "Was `email` written personally to the user by a real person?",
        "criteria": SENDER_QUESTIONS["written_by_person"]["criteria"],
    },
    "record_worth_keeping": {
        "type": "noul",
        "instructions": "Might the user need `email` later as a record or proof?",
        "criteria": SENDER_QUESTIONS["record_worth_keeping"]["criteria"],
    },
}


def sender_state(s):
    """What Jev reads about one sender: who they are and a sample of what they send."""
    state = {
        "sender": {"name": s["name"], "address": s["address"]},
        "sample_emails": [{"subject": e["subject"], "preview": e["preview"]} for e in s["samples"]],
    }
    if s["unsub_share"] >= 0.5:
        state["mailing_list"] = "These emails carry an unsubscribe header, so they were sent to a mailing list."
    if s["replied"]:
        state["user_replied"] = "The user has written back to this sender in at least one of these threads."
    return state


def email_state(s, m):
    return {
        "sender": {"name": s["name"], "address": s["address"]},
        "email": {"subject": m["subject"], "preview": m["snippet"][:300]},
    }
