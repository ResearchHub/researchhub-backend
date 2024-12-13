from unittest.mock import patch

from django.test import TestCase

from utils.locking import LOCK_TIMEOUT, acquire, extend, name, release


class TestLockingFunctions(TestCase):
    @patch("django.core.cache.cache.add")
    def test_acquire_lock_success(self, mock_add):
        """
        Test that acquiring a lock is successful when the key does not exist.
        """
        # Arrange
        mock_add.return_value = True
        lock_key = name("test_lock")

        # Act
        actual = acquire(lock_key, timeout=LOCK_TIMEOUT)

        # Assert
        self.assertTrue(actual)
        mock_add.assert_called_once_with(lock_key, True, LOCK_TIMEOUT)

    @patch("django.core.cache.cache.add")
    def test_acquire_lock_failure(self, mock_add):
        """
        Test that acquiring a lock is unsuccessful when the key already exists.
        """
        # Arrange
        mock_add.return_value = False
        lock_key = name("test_lock")

        # Act
        actual = acquire(lock_key, timeout=LOCK_TIMEOUT)

        # Assert
        self.assertFalse(actual)
        mock_add.assert_called_once_with(lock_key, True, LOCK_TIMEOUT)

    @patch("django.core.cache.cache.touch")
    def test_extend_lock_success(self, mock_touch):
        """
        Test that extending a lock is successful when the key exists.
        """
        # Arrange
        mock_touch.return_value = True
        lock_key = name("test_lock")

        # Act
        actual = extend(lock_key, timeout=LOCK_TIMEOUT)

        # Assert
        self.assertTrue(actual)
        mock_touch.assert_called_once_with(lock_key, LOCK_TIMEOUT)

    @patch("django.core.cache.cache.touch")
    def test_extend_lock_failure(self, mock_touch):
        """
        Test that extending a lock is unsuccessful when the key does not exist.
        """
        # Arrange
        mock_touch.return_value = False
        lock_key = name("test_lock")

        # Act
        actual = extend(lock_key, timeout=LOCK_TIMEOUT)

        # Assert
        self.assertFalse(actual)
        mock_touch.assert_called_once_with(lock_key, LOCK_TIMEOUT)

    @patch("django.core.cache.cache.delete")
    def test_release_lock(self, mock_delete):
        """
        Test that releasing a lock is successful.
        """
        # Arrange
        lock_key = name("test_lock")

        # Act
        release(lock_key)

        # Assert
        mock_delete.assert_called_once_with(lock_key)

    def test_name_function(self):
        """
        Test that the name function formats the lock key correctly.
        """
        # Act
        result = name("test_lock")

        # Assert
        self.assertEqual(result, "lock:test_lock")
