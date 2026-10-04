"""Owned equipment, future combinations and frozen replay use only synthetic facts."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from contracts import DomainError, canonical, digest
from services.evaluation.domain import evaluate, intent
from services.knowledge.app import Knowledge
from services.profile.app import Profile
from services.profile.domain import build_fingerprint, snapshot
from storage import connect

ROOT = Path(__file__).resolve().parents[1]
DEMO = json.loads((ROOT / 'fixtures/demo.json').read_text(encoding='utf-8'))
PACK = json.loads((ROOT / 'knowledge-packs/synthetic-leveling-1.0.0.json').read_text(encoding='utf-8'))


def owned_item(facts, instance_id='owned-robe', slot='body'):
    item = deepcopy(facts['candidate_item'])
    item.update(instance_id=instance_id, name='Synthetic owned support', slot=slot,
                required_level=1, effects=[], affixes=[], embedded_items=[], unknowns=[],
                unrevealed_properties=[], set_id='fixture-archive',
                upgrade_state={'known': True, 'level': 0}, socket_state={'known': True, 'count': 0})
    item.pop('class_id', None)
    return item


def combination():
    facts, purpose = deepcopy(DEMO['facts']), deepcopy(DEMO['intent'])
    facts['equipped_items'] = {'weapon': facts['equipped_items']['weapon']}
    facts['candidate_item'].update(effects=[], set_id='fixture-archive')
    facts['inventory_items'] = [owned_item(facts)]
    purpose['allowed_build_changes'] = ['equipment']
    purpose['future_builds'] = [{'skills': [entry['id'] for entry in facts['skills'] if entry['rank'] > 0],
                               'conditions': deepcopy(facts['conditions']), 'feasibility': 'owned',
                               'equipment_items': ['owned-robe']}]
    return facts, purpose


def run(facts, purpose=None, pack=None, version='0.1.6'):
    pack = deepcopy(pack or PACK)
    profile = {'contract_version': 1, 'profile_id': 'owned-fixture', 'revision': 1,
               'facts': facts, 'facts_hash': digest(facts)}
    return evaluate(profile, {'pack': pack, 'pack_hash': digest(pack)},
                    deepcopy(purpose or DEMO['intent']), evaluator_version=version)


class OwnedInventoryTests(unittest.TestCase):
    def setUp(self):
        self.facts, self.purpose = combination()

    def test_inventory_is_validated_without_normalizing_historical_facts(self):
        snapshot(self.facts)
        legacy = deepcopy(self.facts)
        legacy.pop('inventory_items')
        before = digest(legacy)
        self.assertIs(legacy, snapshot(legacy))
        self.assertEqual(before, digest(legacy))
        self.assertNotIn('inventory_items', legacy)

    def test_inventory_must_be_a_list(self):
        for value in (None, {}, 'unknown'):
            facts = deepcopy(self.facts)
            facts['inventory_items'] = value
            with self.subTest(value=value), self.assertRaisesRegex(DomainError, 'inventory_items_required'):
                snapshot(facts)

    def test_template_cannot_be_recorded_as_owned(self):
        self.facts['inventory_items'][0]['record_kind'] = 'item_template'
        with self.assertRaisesRegex(DomainError, 'actual_item_instance_required'):
            snapshot(self.facts)

    def test_inventory_requires_known_evidence(self):
        self.facts['inventory_items'][0]['evidence_ids'] = ['missing-evidence']
        with self.assertRaisesRegex(DomainError, 'fact_evidence_required'):
            snapshot(self.facts)

    def test_one_instance_cannot_be_counted_twice_or_as_both_worn_and_stored(self):
        for duplicate in (self.facts['inventory_items'][0], self.facts['candidate_item'],
                          self.facts['equipped_items']['weapon']):
            facts = deepcopy(self.facts)
            facts['inventory_items'].append(deepcopy(duplicate))
            with self.subTest(instance=duplicate['instance_id']), self.assertRaisesRegex(DomainError, 'duplicate_item_instance'):
                snapshot(facts)

    def test_unrecorded_inventory_is_not_confirmed_empty(self):
        self.facts.pop('inventory_items')
        result = run(self.facts)
        self.assertIn('inventory_not_recorded', result['blockers'])
        self.assertEqual('needs_confirmation', result['retention'])
        self.assertNotIn('inventory_not_recorded', run(self.facts, version='0.1.5')['blockers'])

    def test_partial_and_unknown_empty_inventory_are_not_complete(self):
        for coverage in ('unknown', 'partial'):
            facts = deepcopy(self.facts)
            facts['inventory_items'] = []
            facts['inventory_coverage'] = coverage
            with self.subTest(coverage=coverage):
                self.assertIn('inventory_not_fully_scanned', run(facts)['blockers'])

    def test_explicit_complete_empty_inventory_can_be_recorded(self):
        self.facts['inventory_items'] = []
        result = run(self.facts)
        self.assertNotIn('inventory_not_recorded', result['blockers'])
        self.assertNotIn('inventory_not_fully_scanned', result['blockers'])

    def test_stored_effects_do_not_become_current_build_providers(self):
        self.facts['candidate_item'].pop('set_id')
        self.facts['inventory_items'][0]['effects'] = ['fixture-fire-focus']
        self.facts['inventory_items'][0].pop('set_id')
        self.facts['skills'] = [{'id': 'fixture-fire-bolt', 'rank': 1, 'effects': [],
                                'evidence_ids': self.facts['evidence_ids']}]
        result = run(self.facts)
        for phase in ('before', 'after'):
            self.assertFalse(any(row['state'] == 'active' and row['capability'] == 'fire_focus'
                                 for row in result['comparison'][phase]))
        self.assertFalse(any('owned-robe' in row['source_ids'] for row in result['comparison']['after']))

    def test_inventory_change_does_not_change_equipped_build_identity(self):
        before = build_fingerprint(self.facts)
        self.facts['inventory_items'][0]['upgrade_state']['level'] = 5
        self.assertEqual(before, build_fingerprint(self.facts))

    def test_legacy_untyped_inventory_cannot_be_served_as_confirmed_owned_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Profile(Path(directory))
            profile.observe({'observation_id': 'demo-text', 'method': 'text', 'raw_text': 'Synthetic old profile'})
            result = profile.confirm({'request_id': 'legacy-seed', 'profile_id': 'legacy-owned',
                                      'observation_id': 'demo-text', 'expected_revision': 0,
                                      'player_confirmed': True, 'facts': self.facts})
            # Simulate a v1 extension accepted before inventory had a validated type.
            result['facts']['inventory_items'] = 'previously-untyped-extension'
            result['facts_hash'] = digest(result['facts'])
            with connect(profile.database) as db:
                db.execute('UPDATE revisions SET payload=? WHERE profile_id=? AND revision=1',
                           (canonical(result), 'legacy-owned'))
            with self.assertRaisesRegex(DomainError, 'inventory_items_required'):
                Profile(Path(directory)).read('legacy-owned', 1)
            with connect(profile.database) as db:
                stored = json.loads(db.execute('SELECT payload FROM revisions WHERE profile_id=? AND revision=1',
                                               ('legacy-owned',)).fetchone()[0])
            self.assertEqual('previously-untyped-extension', stored['facts']['inventory_items'])

    def test_inventory_survives_sqlite_restart_and_old_revisions_remain_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Profile(Path(directory))
            profile.observe({'observation_id': 'demo-text', 'method': 'text', 'raw_text': 'Synthetic owned equipment'})
            body = {'request_id': 'confirm-owned', 'profile_id': 'owned-fixture', 'observation_id': 'demo-text',
                    'expected_revision': 0, 'player_confirmed': True, 'facts': self.facts}
            first = profile.confirm(body)
            body = deepcopy(body)
            body.update(request_id='confirm-owned-2', expected_revision=1)
            body['facts']['inventory_items'][0]['upgrade_state']['level'] = 3
            second = profile.confirm(body)
            reopened = Profile(Path(directory))
            self.assertEqual(first, reopened.read('owned-fixture', 1))
            self.assertEqual(second, reopened.read('owned-fixture', 2))
            self.assertEqual(0, first['facts']['inventory_items'][0]['upgrade_state']['level'])
            self.assertEqual(3, second['facts']['inventory_items'][0]['upgrade_state']['level'])
            self.assertEqual(first['build_hash'], second['build_hash'])


class FutureOwnedEquipmentTests(unittest.TestCase):
    def setUp(self):
        self.facts, self.purpose = combination()

    def test_owned_support_completes_candidate_set_only_in_selected_future(self):
        original = digest(self.facts)
        result = run(self.facts, self.purpose)
        self.assertEqual('candidate', result['retention'])
        future = next(row for row in result['reasons'] if row['kind'] == 'future_use' and row['capability'] == 'archive_shield')
        self.assertEqual(['owned-robe'], [item['instance_id'] for item in future['future_equipment']])
        self.assertEqual({'owned-robe', self.facts['candidate_item']['instance_id']}, set(future['source_ids']))
        self.assertTrue(set(self.facts['inventory_items'][0]['evidence_ids']).issubset(future['input_evidence_ids']))
        self.assertFalse(any(row['state'] == 'active' and row['capability'] == 'archive_shield'
                             for row in result['comparison']['after']))
        self.assertEqual(original, digest(self.facts))

    def test_merely_owning_support_without_selecting_it_does_not_complete_future(self):
        self.purpose['future_builds'][0]['equipment_items'] = []
        self.assertEqual('low_current_relevance', run(self.facts, self.purpose)['retention'])

    def test_selected_support_cannot_be_invented_from_an_owned_label(self):
        self.purpose['future_builds'][0]['equipment_items'] = ['not-recorded']
        result = run(self.facts, self.purpose)
        self.assertIn('future_item_not_owned:not-recorded', result['blockers'])
        self.assertEqual('needs_confirmation', result['retention'])
        self.assertFalse(any(row['kind'] == 'future_use' for row in result['reasons']))

    def test_equipment_changes_need_explicit_permission(self):
        self.purpose['allowed_build_changes'] = ['skills']
        result = run(self.facts, self.purpose)
        self.assertIn('future_build_change_not_permitted', result['blockers'])
        self.assertEqual('needs_confirmation', result['retention'])

    def test_two_selected_items_cannot_occupy_one_slot(self):
        self.facts['inventory_items'].append(owned_item(self.facts, 'another-robe'))
        self.purpose['future_builds'][0]['equipment_items'].append('another-robe')
        result = run(self.facts, self.purpose)
        self.assertIn('future_equipment_slot_conflict:body', result['blockers'])
        self.assertFalse(any(row['kind'] == 'future_use' for row in result['reasons']))

    def test_support_cannot_replace_the_candidate_under_evaluation(self):
        self.facts['inventory_items'][0]['slot'] = 'weapon'
        result = run(self.facts, self.purpose)
        self.assertIn('future_candidate_slot_conflict:weapon', result['blockers'])
        self.assertEqual('needs_confirmation', result['retention'])

    def test_candidate_for_other_class_cannot_supply_current_or_future_use(self):
        self.facts['candidate_item']['class_id'] = 'other-class'
        result = run(self.facts, self.purpose)
        self.assertIn('candidate_class_incompatible', result['blockers'])
        self.assertEqual('needs_confirmation', result['retention'])
        self.assertFalse(result['comparison']['scope_compatible'])
        self.assertEqual([], result['reasons'])
        self.assertEqual([], result['comparison']['after'])

    def test_future_support_class_and_level_requirements_are_checked(self):
        for field, value, blocker in (('required_level', 99, 'future_required_level_not_met:owned-robe'),
                                      ('class_id', 'other-class', 'future_item_class_incompatible:owned-robe')):
            facts = deepcopy(self.facts)
            facts['inventory_items'][0][field] = value
            result = run(facts, self.purpose)
            with self.subTest(field=field):
                self.assertIn(blocker, result['blockers'])
                self.assertEqual('needs_confirmation', result['retention'])

    def test_unknown_selected_support_does_not_establish_a_definitive_verdict(self):
        for field, value, blocker in (('unknowns', ['unmapped'], 'item_unknown:unmapped'),
                                      ('required_level', None, 'required_level_unknown:owned-robe'),
                                      ('effects', ['unmapped'], 'unknown_effect:unmapped')):
            facts = deepcopy(self.facts)
            facts['inventory_items'][0][field] = value
            result = run(facts, self.purpose)
            with self.subTest(field=field):
                self.assertIn(blocker, result['blockers'])
                self.assertEqual('needs_confirmation', result['retention'])

    def test_future_references_have_a_strict_wire_shape(self):
        for refs, error in (({}, 'future_equipment_required'), (['owned-robe', 'owned-robe'], 'duplicate_future_equipment'),
                            (['not an identifier'], 'invalid_identifier')):
            purpose = deepcopy(self.purpose)
            purpose['future_builds'][0]['equipment_items'] = refs
            with self.subTest(refs=refs), self.assertRaisesRegex(DomainError, error):
                intent(purpose)

    def test_unchanged_allocated_skill_keeps_its_actor_in_future(self):
        self.facts['skills'][0]['actor'] = 'companion'
        self.facts['candidate_item'].pop('set_id')
        self.facts['candidate_item']['effects'] = ['fixture-cold-focus']
        self.purpose['future_builds'][0]['equipment_items'] = []
        result = run(self.facts, self.purpose)
        self.assertEqual('low_current_relevance', result['retention'])
        self.assertFalse(any(row['kind'] == 'future_use' for row in result['reasons']))

    def test_locked_future_combination_is_identical_on_ten_replays(self):
        expected = digest(run(self.facts, self.purpose))
        for _ in range(10):
            self.assertEqual(expected, digest(run(self.facts, self.purpose)))

    def test_owned_inventory_does_not_enable_research_game_rules(self):
        pack = json.loads((ROOT / 'knowledge-packs/deskrawl-sorcerer-leveling-0.6.0-research.json').read_text(encoding='utf-8'))
        self.facts['context'] = deepcopy(pack['context'])
        result = run(self.facts, self.purpose, pack=pack)
        self.assertIn('game_mechanics_not_accepted', result['blockers'])
        self.assertEqual([], result['comparison']['after'])
        self.assertEqual([], result['reasons'])


if __name__ == '__main__':
    unittest.main()
