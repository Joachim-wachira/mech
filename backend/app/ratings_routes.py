"""
Mech Platform — Ratings Routes
Blueprint: ratings_bp  →  registered at /api/ratings in __init__.py

Business rules (all enforced here):
  - Only drivers  : POST /api/ratings/submit
  - Mechanic only : GET  /api/ratings/mechanic/my-ratings   (own ratings only)
  - SpareShop only: GET  /api/ratings/spareshop/my-ratings  (own ratings only)
  - Admin only    : PATCH/PUT/DELETE /api/ratings/<id>
  - Admin only    : GET  /api/ratings/admin/all
"""

from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import User

ratings_bp = Blueprint("ratings", __name__)


def _get_user(user_id):
    """Fetch a User by id (JWT identity is a string — cast to int). Returns None if not found."""
    from app.models import User
    try:
        return User.query.get(int(user_id))
    except (TypeError, ValueError):
        return None


# ── Submit / Update Rating ────────────────────────────────────────
@ratings_bp.route("/submit", methods=["POST"])
@jwt_required()
def submit_rating():
    """
    Driver submits a rating for a mechanic or spare shop.
    One rating per driver per target — subsequent calls update the existing rating.
    """
    from app import db
    from app.models import Rating

    user_id  = get_jwt_identity()
    reviewer = _get_user(user_id)

    if not reviewer or reviewer.role != "driver":
        return jsonify({"error": "Only drivers can submit ratings"}), 403

    data      = request.get_json(silent=True) or {}
    target_id = data.get("target_id")
    stars     = data.get("stars")
    comment   = str(data.get("comment", "")).strip()

    if not target_id:
        return jsonify({"error": "target_id is required"}), 400
    if stars not in (1, 2, 3, 4, 5):
        return jsonify({"error": "stars must be an integer 1–5"}), 400

    target = _get_user(target_id)
    if not target or target.role not in ("mechanic", "spareshop"):
        return jsonify({"error": "Target must be a mechanic or spare shop"}), 400

    try:
        existing = Rating.query.filter_by(reviewer_id=user_id, target_id=target_id).first()
        if existing:
            existing.stars      = stars
            existing.comment    = comment
            existing.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify({"message": "Rating updated", "rating_id": existing.id}), 200
        else:
            rating = Rating(
                reviewer_id   = user_id,
                reviewer_name = reviewer.full_name,
                target_id     = target_id,
                target_role   = target.role,
                stars         = stars,
                comment       = comment,
                created_at    = datetime.now(timezone.utc),
            )
            db.session.add(rating)
            db.session.commit()
            return jsonify({"message": "Rating submitted", "rating_id": rating.id}), 201
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f"[ratings submit] {exc}")
        return jsonify({"error": "Could not save rating"}), 500


# ── Mechanic: read own ratings ────────────────────────────────────
@ratings_bp.route("/mechanic/my-ratings", methods=["GET"])
@jwt_required()
def mechanic_my_ratings():
    """Returns the authenticated mechanic's own ratings (submitted by drivers)."""
    from app import db
    from app.models import Rating

    user_id = get_jwt_identity()
    user    = _get_user(user_id)

    if not user or user.role != "mechanic":
        return jsonify({"error": "Access denied — mechanics only"}), 403

    try:
        ratings    = (Rating.query
                      .filter_by(target_id=user_id, target_role="mechanic")
                      .order_by(Rating.created_at.desc())
                      .all())
        stars_list = [r.stars for r in ratings]
        avg        = round(sum(stars_list) / len(stars_list), 1) if stars_list else 0.0

        return jsonify({
            "average_rating": avg,
            "total_reviews":  len(ratings),
            "reviews": [
                {
                    "id":            r.id,
                    "reviewer_name": r.reviewer_name,
                    "stars":         r.stars,
                    "comment":       r.comment,
                    "created_at":    r.created_at.strftime("%d %b %Y") if r.created_at else "",
                }
                for r in ratings
            ],
        }), 200
    except Exception as exc:
        current_app.logger.error(f"[mechanic ratings] {exc}")
        return jsonify({"average_rating": 0, "total_reviews": 0, "reviews": []}), 200


# ── Spare Shop: read own ratings ──────────────────────────────────
@ratings_bp.route("/spareshop/my-ratings", methods=["GET"])
@jwt_required()
def spareshop_my_ratings():
    """Returns the authenticated spare shop's own ratings (submitted by drivers)."""
    from app import db
    from app.models import Rating

    user_id = get_jwt_identity()
    user    = _get_user(user_id)

    if not user or user.role != "spareshop":
        return jsonify({"error": "Access denied — spare shops only"}), 403

    try:
        ratings    = (Rating.query
                      .filter_by(target_id=user_id, target_role="spareshop")
                      .order_by(Rating.created_at.desc())
                      .all())
        stars_list = [r.stars for r in ratings]
        avg        = round(sum(stars_list) / len(stars_list), 1) if stars_list else 0.0

        return jsonify({
            "average_rating": avg,
            "total_reviews":  len(ratings),
            "reviews": [
                {
                    "id":            r.id,
                    "reviewer_name": r.reviewer_name,
                    "stars":         r.stars,
                    "comment":       r.comment,
                    "created_at":    r.created_at.strftime("%d %b %Y") if r.created_at else "",
                }
                for r in ratings
            ],
        }), 200
    except Exception as exc:
        current_app.logger.error(f"[spareshop ratings] {exc}")
        return jsonify({"average_rating": 0, "total_reviews": 0, "reviews": []}), 200


# ── Admin: edit a rating ──────────────────────────────────────────
@ratings_bp.route("/<int:rating_id>", methods=["PATCH", "PUT"])
@jwt_required()
def admin_update_rating(rating_id):
    """Admin can update stars or comment on any rating."""
    from app import db
    from app.models import Rating

    user_id = get_jwt_identity()
    admin   = _get_user(user_id)

    if not admin or admin.role != "admin":
        return jsonify({"error": "Only admins can modify ratings"}), 403

    rating = Rating.query.get(rating_id)
    if not rating:
        return jsonify({"error": "Rating not found"}), 404

    data = request.get_json(silent=True) or {}
    if "stars" in data:
        if data["stars"] not in (1, 2, 3, 4, 5):
            return jsonify({"error": "stars must be 1–5"}), 400
        rating.stars = data["stars"]
    if "comment" in data:
        rating.comment = str(data["comment"]).strip()

    rating.updated_at  = datetime.now(timezone.utc)
    rating.modified_by = user_id

    try:
        db.session.commit()
        return jsonify({"message": "Rating updated by admin", "rating_id": rating.id}), 200
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f"[admin update rating] {exc}")
        return jsonify({"error": "Could not update rating"}), 500


# ── Admin: delete a rating ────────────────────────────────────────
@ratings_bp.route("/<int:rating_id>", methods=["DELETE"])
@jwt_required()
def admin_delete_rating(rating_id):
    """Admin can permanently delete any rating."""
    from app import db
    from app.models import Rating

    user_id = get_jwt_identity()
    admin   = _get_user(user_id)

    if not admin or admin.role != "admin":
        return jsonify({"error": "Only admins can delete ratings"}), 403

    rating = Rating.query.get(rating_id)
    if not rating:
        return jsonify({"error": "Rating not found"}), 404

    try:
        db.session.delete(rating)
        db.session.commit()
        return jsonify({"message": "Rating deleted"}), 200
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f"[admin delete rating] {exc}")
        return jsonify({"error": "Could not delete rating"}), 500


# ── Admin: list all ratings ───────────────────────────────────────
@ratings_bp.route("/admin/all", methods=["GET"])
@jwt_required()
def admin_all_ratings():
    """Admin can list all ratings with optional filters."""
    from app.models import Rating

    user_id = get_jwt_identity()
    admin   = _get_user(user_id)

    if not admin or admin.role != "admin":
        return jsonify({"error": "Admins only"}), 403

    target_role = request.args.get("role")
    target_id   = request.args.get("target_id")
    min_stars   = request.args.get("min_stars", type=int)

    query = Rating.query
    if target_role:
        query = query.filter_by(target_role=target_role)
    if target_id:
        query = query.filter_by(target_id=int(target_id))
    if min_stars:
        query = query.filter(Rating.stars >= min_stars)

    ratings = query.order_by(Rating.created_at.desc()).limit(200).all()

    # Batch-load target names for display
    target_ids = {r.target_id for r in ratings if r.target_id}
    name_map = {u.id: (u.business_name or u.full_name) for u in User.query.filter(User.id.in_(target_ids)).all()} if target_ids else {}

    return jsonify({
        "ratings": [
            {
                "id":            r.id,
                "reviewer_name": r.reviewer_name,
                "reviewer_id":   r.reviewer_id,
                "target_id":     r.target_id,
                "target_name":   name_map.get(r.target_id, "Unknown"),
                "target_role":   r.target_role,
                "stars":         r.stars,
                "comment":       r.comment,
                "created_at":    r.created_at.isoformat() if r.created_at else None,
            }
            for r in ratings
        ],
        "count": len(ratings),
    }), 200
